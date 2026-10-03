.class public Lcom/sherinlal/splitledger/MainActivity;
.super Landroid/app/Activity;
.implements Ljava/lang/Runnable;
.source "MainActivity.java"

# The whole app: one Activity hosting a WebView that loads assets/index.html.
#
# Native capabilities exposed to the page (AndroidBridge): the contact picker
# (pickContact, askContacts/contacts), Android's share sheet (shareText for
# invite text, shareImage for share cards via ShareProvider), and
# the invite link the app was opened with (pendingLink). The single-contact
# picker, the original one, fires Android's own picker as a separate activity.
#
# The picker alone returns a single number, and on some phones that is whichever
# one the contact app considers primary -- so adding "Murali" could quietly use
# a number he does not carry, and the group would never reach him. To ask
# instead of guess, the app reads the numbers saved against the ONE contact that
# was chosen, which needs READ_CONTACTS. It is requested at the moment Contacts
# is tapped, never at launch. Refusing it is not fatal: the picker still runs
# and whatever number it returns is used, exactly as before.
#
# Runnable is implemented so pickContact() -- which the WebView calls on its
# own binder thread -- can hop to the UI thread without a second class.

.field private w:Landroid/webkit/WebView;

# What run() should do once the contacts permission has been settled:
# 0 = open Android's single-contact picker (pickContact), 1 = tell the page the
# address book can be read now, for its own multi-select picker (askContacts).
.field private mode:I

# A link the app was opened with (an invite: https://.../join/<token> or
# splitbuddy://join/<token>), held until the page asks for it.
.field private link:Ljava/lang/String;

# What the page asked to share, waiting for the UI thread.
.field private shareSubject:Ljava/lang/String;
.field private shareBody:Ljava/lang/String;

# Contact id of the row the picker returned. A field rather than a local
# because onActivityResult is already using all sixteen registers it is allowed.
.field private cid:Ljava/lang/String;


.method public constructor <init>()V
    .registers 1
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method


.method protected onCreate(Landroid/os/Bundle;)V
    .registers 5

    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    iput-object v0, p0, Lcom/sherinlal/splitledger/MainActivity;->w:Landroid/webkit/WebView;

    invoke-virtual {v0}, Landroid/webkit/WebView;->getSettings()Landroid/webkit/WebSettings;
    move-result-object v1

    const/4 v2, 0x1

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setJavaScriptEnabled(Z)V

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setDomStorageEnabled(Z)V

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setDatabaseEnabled(Z)V

    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowFileAccess(Z)V

    # The page is served from file://, whose origin is opaque, so without this
    # the WebView refuses to let it call the sync server at all. Safe here
    # because the only page ever loaded is the one bundled in the APK -- no
    # remote or user-supplied content runs in this WebView.
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowUniversalAccessFromFileURLs(Z)V

    # keep the page clear of the status and navigation bars
    invoke-virtual {v0, v2}, Landroid/webkit/WebView;->setFitsSystemWindows(Z)V

    # the page's only route to native code; @JavascriptInterface gates it to
    # the annotated methods below (pickContact, askContacts, contacts,
    # shareText, shareImage, pendingLink)
    const-string v1, "AndroidBridge"

    invoke-virtual {v0, p0, v1}, Landroid/webkit/WebView;->addJavascriptInterface(Ljava/lang/Object;Ljava/lang/String;)V

    invoke-virtual {p0, v0}, Lcom/sherinlal/splitledger/MainActivity;->setContentView(Landroid/view/View;)V

    # opened from an invite link? keep it for the page
    invoke-virtual {p0}, Lcom/sherinlal/splitledger/MainActivity;->getIntent()Landroid/content/Intent;
    move-result-object v1

    invoke-direct {p0, v1}, Lcom/sherinlal/splitledger/MainActivity;->remember(Landroid/content/Intent;)V

    const-string v1, "file:///android_asset/index.html"

    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    return-void
.end method


# Called from the WebView's binder thread. Hop to the UI thread to start the
# picker.
.method public pickContact()V
    .registers 2
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    const/4 v0, 0x0

    iput v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    invoke-virtual {p0, p0}, Lcom/sherinlal/splitledger/MainActivity;->runOnUiThread(Ljava/lang/Runnable;)V

    return-void
.end method


# The multi-select picker's way in: settle the contacts permission exactly as
# pickContact does (asked now, on tap, never at launch), then call the page's
# window.__contactsReady(), which reads the list with contacts() below.
.method public askContacts()V
    .registers 2
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    const/4 v0, 0x1

    iput v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    invoke-virtual {p0, p0}, Lcom/sherinlal/splitledger/MainActivity;->runOnUiThread(Ljava/lang/Runnable;)V

    return-void
.end method


# The address book as text (see Contacts.list), or "!" without permission.
# Anything at all going wrong in there -- including the Contacts class itself
# failing to load -- comes back as "?", and the page offers the one-at-a-time
# picker instead. It must never take the app down.
.method public contacts()Ljava/lang/String;
    .registers 2
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    :try_start_0
    invoke-static {p0}, Lcom/sherinlal/splitledger/Contacts;->list(Landroid/content/Context;)Ljava/lang/String;
    move-result-object v0
    :try_end_0
    .catch Ljava/lang/Throwable; {:try_start_0 .. :try_end_0} :catch_0

    return-object v0

    :catch_0
    move-exception v0

    const-string v0, "?"

    return-object v0
.end method


# ---------------------------------------------------------------- sharing
#
# The page asks to share a piece of text (a group invite); Android's own share
# sheet does the rest, so WhatsApp, Gmail, Messages and anything else
# installed that takes text appear by themselves. No permission is involved.
.method public shareText(Ljava/lang/String;Ljava/lang/String;)V
    .registers 4
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    iput-object p1, p0, Lcom/sherinlal/splitledger/MainActivity;->shareSubject:Ljava/lang/String;

    iput-object p2, p0, Lcom/sherinlal/splitledger/MainActivity;->shareBody:Ljava/lang/String;

    const/4 v0, 0x2

    iput v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    invoke-virtual {p0, p0}, Lcom/sherinlal/splitledger/MainActivity;->runOnUiThread(Ljava/lang/Runnable;)V

    return-void
.end method


# On the UI thread: ACTION_SEND text/plain, through the chooser.
.method private doShare()V
    .registers 6

    :try_start_0
    new-instance v0, Landroid/content/Intent;

    const-string v1, "android.intent.action.SEND"

    invoke-direct {v0, v1}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    const-string v1, "text/plain"

    invoke-virtual {v0, v1}, Landroid/content/Intent;->setType(Ljava/lang/String;)Landroid/content/Intent;

    const-string v1, "android.intent.extra.SUBJECT"

    iget-object v2, p0, Lcom/sherinlal/splitledger/MainActivity;->shareSubject:Ljava/lang/String;

    if-nez v2, :have_subject

    const-string v2, ""

    :have_subject
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    const-string v1, "android.intent.extra.TEXT"

    iget-object v2, p0, Lcom/sherinlal/splitledger/MainActivity;->shareBody:Ljava/lang/String;

    if-nez v2, :have_body

    const-string v2, ""

    :have_body
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    const-string v1, "Share group"

    invoke-static {v0, v1}, Landroid/content/Intent;->createChooser(Landroid/content/Intent;Ljava/lang/CharSequence;)Landroid/content/Intent;
    move-result-object v3

    invoke-virtual {p0, v3}, Lcom/sherinlal/splitledger/MainActivity;->startActivity(Landroid/content/Intent;)V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    return-void

    # nothing on the phone can take it: tell the page, which offers Copy link
    :catch_0
    move-exception v0

    iget-object v1, p0, Lcom/sherinlal/splitledger/MainActivity;->w:Landroid/webkit/WebView;

    if-eqz v1, :done

    const-string v2, "javascript:if(window.__shareFailed)window.__shareFailed()"

    invoke-virtual {v1, v2}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    :done
    return-void
.end method


# ------------------------------------------------------------ share cards
#
# The page draws a card (an expense, a balance, a group summary) and hands it
# over as base64 PNG. It is written to the app's private cache — one file,
# overwritten each time, never kept — and shared as
# content://com.sherinlal.splitledger.share/split-buddy-card.png through
# ShareProvider, with read permission granted only to the app the person
# picks. Returns "ok" once the file is written, "error" if it could not be.
.method public shareImage(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    .registers 9
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    :try_start_0
    const/4 v0, 0x0

    invoke-static {p1, v0}, Landroid/util/Base64;->decode(Ljava/lang/String;I)[B
    move-result-object v0

    invoke-virtual {p0}, Lcom/sherinlal/splitledger/MainActivity;->getCacheDir()Ljava/io/File;
    move-result-object v2

    new-instance v1, Ljava/io/File;

    const-string v3, "share"

    invoke-direct {v1, v2, v3}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    invoke-virtual {v1}, Ljava/io/File;->mkdirs()Z

    new-instance v2, Ljava/io/File;

    const-string v3, "split-buddy-card.png"

    invoke-direct {v2, v1, v3}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v3, Ljava/io/FileOutputStream;

    invoke-direct {v3, v2}, Ljava/io/FileOutputStream;-><init>(Ljava/io/File;)V

    invoke-virtual {v3, v0}, Ljava/io/FileOutputStream;->write([B)V

    invoke-virtual {v3}, Ljava/io/FileOutputStream;->close()V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    iput-object p2, p0, Lcom/sherinlal/splitledger/MainActivity;->shareBody:Ljava/lang/String;

    const/4 v0, 0x3

    iput v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    invoke-virtual {p0, p0}, Lcom/sherinlal/splitledger/MainActivity;->runOnUiThread(Ljava/lang/Runnable;)V

    const-string v0, "ok"

    return-object v0

    :catch_0
    move-exception v0

    const-string v0, "error"

    return-object v0
.end method


# On the UI thread: ACTION_SEND image/png with the content:// URI, the
# caption as EXTRA_TEXT (an extra; the image alone carries everything), and a
# one-off read grant for whichever app receives it.
.method private doShareImage()V
    .registers 7

    :try_start_0
    const-string v0, "content://com.sherinlal.splitledger.share/split-buddy-card.png"

    invoke-static {v0}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v0

    new-instance v1, Landroid/content/Intent;

    const-string v2, "android.intent.action.SEND"

    invoke-direct {v1, v2}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V

    const-string v2, "image/png"

    invoke-virtual {v1, v2}, Landroid/content/Intent;->setType(Ljava/lang/String;)Landroid/content/Intent;

    const-string v2, "android.intent.extra.STREAM"

    invoke-virtual {v1, v2, v0}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Landroid/os/Parcelable;)Landroid/content/Intent;

    iget-object v2, p0, Lcom/sherinlal/splitledger/MainActivity;->shareBody:Ljava/lang/String;

    if-eqz v2, :no_caption

    invoke-virtual {v2}, Ljava/lang/String;->length()I
    move-result v3

    if-eqz v3, :no_caption

    const-string v3, "android.intent.extra.TEXT"

    invoke-virtual {v1, v3, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;

    :no_caption
    # FLAG_GRANT_READ_URI_PERMISSION, carried through the chooser by ClipData
    const/4 v2, 0x1

    invoke-virtual {v1, v2}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;

    const-string v2, "Split Buddy"

    invoke-static {v2, v0}, Landroid/content/ClipData;->newRawUri(Ljava/lang/CharSequence;Landroid/net/Uri;)Landroid/content/ClipData;
    move-result-object v2

    invoke-virtual {v1, v2}, Landroid/content/Intent;->setClipData(Landroid/content/ClipData;)V

    const-string v2, "Share card"

    invoke-static {v1, v2}, Landroid/content/Intent;->createChooser(Landroid/content/Intent;Ljava/lang/CharSequence;)Landroid/content/Intent;
    move-result-object v3

    const/4 v2, 0x1

    invoke-virtual {v3, v2}, Landroid/content/Intent;->addFlags(I)Landroid/content/Intent;

    invoke-virtual {p0, v3}, Lcom/sherinlal/splitledger/MainActivity;->startActivity(Landroid/content/Intent;)V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    return-void

    :catch_0
    move-exception v0

    iget-object v1, p0, Lcom/sherinlal/splitledger/MainActivity;->w:Landroid/webkit/WebView;

    if-eqz v1, :done

    const-string v2, "javascript:if(window.__shareFailed)window.__shareFailed()"

    invoke-virtual {v1, v2}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    :done
    return-void
.end method


# ------------------------------------------------------------- invite links
#
# The link the app was opened with, once: the page reads it on start-up and
# again whenever onNewIntent says another one has arrived.
.method public pendingLink()Ljava/lang/String;
    .registers 3
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    iget-object v0, p0, Lcom/sherinlal/splitledger/MainActivity;->link:Ljava/lang/String;

    const/4 v1, 0x0

    iput-object v1, p0, Lcom/sherinlal/splitledger/MainActivity;->link:Ljava/lang/String;

    if-nez v0, :have

    const-string v0, ""

    :have
    return-object v0
.end method


.method private remember(Landroid/content/Intent;)V
    .registers 3

    if-eqz p1, :done

    invoke-virtual {p1}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0

    if-eqz v0, :done

    invoke-virtual {v0}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v0

    iput-object v0, p0, Lcom/sherinlal/splitledger/MainActivity;->link:Ljava/lang/String;

    :done
    return-void
.end method


# The app is singleTask, so a link tapped while it is already running arrives
# here rather than in onCreate.
.method protected onNewIntent(Landroid/content/Intent;)V
    .registers 4

    invoke-super {p0, p1}, Landroid/app/Activity;->onNewIntent(Landroid/content/Intent;)V

    invoke-virtual {p0, p1}, Lcom/sherinlal/splitledger/MainActivity;->setIntent(Landroid/content/Intent;)V

    invoke-direct {p0, p1}, Lcom/sherinlal/splitledger/MainActivity;->remember(Landroid/content/Intent;)V

    iget-object v0, p0, Lcom/sherinlal/splitledger/MainActivity;->w:Landroid/webkit/WebView;

    if-eqz v0, :done

    const-string v1, "javascript:if(window.__linkArrived)window.__linkArrived()"

    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    :done
    return-void
.end method


# Permission settled (granted or not): do what was asked for.
.method private proceed()V
    .registers 4

    iget v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    if-eqz v0, :pick

    const/4 v0, 0x0

    iput v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    iget-object v1, p0, Lcom/sherinlal/splitledger/MainActivity;->w:Landroid/webkit/WebView;

    if-eqz v1, :done

    const-string v2, "javascript:if(window.__contactsReady)window.__contactsReady()"

    invoke-virtual {v1, v2}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    :done
    return-void

    :pick
    invoke-direct {p0}, Lcom/sherinlal/splitledger/MainActivity;->startPicker()V

    return-void
.end method


# On the UI thread. Make sure the permission question has been asked before the
# picker opens, so that by the time a contact comes back the app either can read
# its other numbers or knows it cannot.
.method public run()V
    # FIVE registers, not four. With one parameter, .registers 4 puts `this` in
    # v3 -- and the array index below writes v3. That overwrote `this` with the
    # integer 8, and the next invoke-virtual tried to call a method on a number:
    #   VerifyError ... tried to get class from non-reference register v3
    # The app would not start at all. Locals must stay below the parameters.
    .registers 5

    # mode 3: share the card image the page just wrote (no permission needed)
    iget v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    const/4 v1, 0x3

    if-ne v0, v1, :cond_not_image

    const/4 v0, 0x0

    iput v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    invoke-direct {p0}, Lcom/sherinlal/splitledger/MainActivity;->doShareImage()V

    return-void

    :cond_not_image
    # mode 2 is a share request, which needs no permission at all
    iget v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    const/4 v1, 0x2

    if-ne v0, v1, :cond_not_share

    const/4 v0, 0x0

    iput v0, p0, Lcom/sherinlal/splitledger/MainActivity;->mode:I

    invoke-direct {p0}, Lcom/sherinlal/splitledger/MainActivity;->doShare()V

    return-void

    :cond_not_share

    const-string v0, "android.permission.READ_CONTACTS"

    invoke-virtual {p0, v0}, Lcom/sherinlal/splitledger/MainActivity;->checkSelfPermission(Ljava/lang/String;)I
    move-result v1

    if-eqz v1, :cond_have

    const/4 v2, 0x1

    new-array v2, v2, [Ljava/lang/String;

    const/4 v3, 0x0

    aput-object v0, v2, v3

    const/16 v3, 0x8

    invoke-virtual {p0, v2, v3}, Lcom/sherinlal/splitledger/MainActivity;->requestPermissions([Ljava/lang/String;I)V

    return-void

    :cond_have
    invoke-direct {p0}, Lcom/sherinlal/splitledger/MainActivity;->proceed()V

    return-void
.end method


# Whatever the answer, open the picker. Granted means the numbers can be listed;
# denied means one number comes back and the app carries on as it always did.
.method public onRequestPermissionsResult(I[Ljava/lang/String;[I)V
    .registers 5

    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onRequestPermissionsResult(I[Ljava/lang/String;[I)V

    const/16 v0, 0x8

    if-eq p1, v0, :cond_ours

    return-void

    :cond_ours
    invoke-direct {p0}, Lcom/sherinlal/splitledger/MainActivity;->proceed()V

    return-void
.end method


.method private startPicker()V
    .registers 4

    :try_start_0
    new-instance v0, Landroid/content/Intent;

    const-string v1, "android.intent.action.PICK"

    sget-object v2, Landroid/provider/ContactsContract$CommonDataKinds$Phone;->CONTENT_URI:Landroid/net/Uri;

    invoke-direct {v0, v1, v2}, Landroid/content/Intent;-><init>(Ljava/lang/String;Landroid/net/Uri;)V

    const/4 v1, 0x7

    invoke-virtual {p0, v0, v1}, Lcom/sherinlal/splitledger/MainActivity;->startActivityForResult(Landroid/content/Intent;I)V
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    return-void

    # no contacts app, or it refused to open: tell the page so it can stop waiting
    :catch_0
    move-exception v0

    const-string v0, ""

    invoke-direct {p0, v0, v0}, Lcom/sherinlal/splitledger/MainActivity;->sendPick(Ljava/lang/String;Ljava/lang/String;)V

    return-void
.end method


.method protected onActivityResult(IILandroid/content/Intent;)V
    .registers 16

    invoke-super {p0, p1, p2, p3}, Landroid/app/Activity;->onActivityResult(IILandroid/content/Intent;)V

    const/4 v0, 0x7

    if-eq p1, v0, :cond_ours

    return-void

    :cond_ours
    const-string v1, ""

    const-string v2, ""

    # "" until the cursor tells us otherwise
    iput-object v1, p0, Lcom/sherinlal/splitledger/MainActivity;->cid:Ljava/lang/String;

    const/4 v0, -0x1

    if-ne p2, v0, :cond_send

    if-eqz p3, :cond_send

    invoke-virtual {p3}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v3

    if-eqz v3, :cond_send

    :try_start_0
    invoke-virtual {p0}, Lcom/sherinlal/splitledger/MainActivity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v4

    move-object v5, v3

    const/4 v6, 0x0

    const/4 v7, 0x0

    const/4 v8, 0x0

    const/4 v9, 0x0

    invoke-virtual/range {v4 .. v9}, Landroid/content/ContentResolver;->query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;
    move-result-object v10

    if-eqz v10, :cond_endtry

    invoke-interface {v10}, Landroid/database/Cursor;->moveToFirst()Z
    move-result v11

    if-eqz v11, :cond_close

    const-string v0, "display_name"

    invoke-interface {v10, v0}, Landroid/database/Cursor;->getColumnIndex(Ljava/lang/String;)I
    move-result v11

    if-ltz v11, :cond_num

    invoke-interface {v10, v11}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v1

    :cond_num
    const-string v0, "data1"

    invoke-interface {v10, v0}, Landroid/database/Cursor;->getColumnIndex(Ljava/lang/String;)I
    move-result v11

    if-ltz v11, :cond_cid

    invoke-interface {v10, v11}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v2

    # which contact this number belongs to, so its siblings can be listed
    :cond_cid
    const-string v0, "contact_id"

    invoke-interface {v10, v0}, Landroid/database/Cursor;->getColumnIndex(Ljava/lang/String;)I
    move-result v11

    if-ltz v11, :cond_close

    invoke-interface {v10, v11}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v0

    iput-object v0, p0, Lcom/sherinlal/splitledger/MainActivity;->cid:Ljava/lang/String;

    :cond_close
    invoke-interface {v10}, Landroid/database/Cursor;->close()V

    :cond_endtry
    nop
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    goto :cond_send

    :catch_0
    move-exception v0

    :cond_send
    iget-object v0, p0, Lcom/sherinlal/splitledger/MainActivity;->cid:Ljava/lang/String;

    invoke-direct {p0, v0, v2}, Lcom/sherinlal/splitledger/MainActivity;->numbersFor(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    invoke-direct {p0, v1, v2}, Lcom/sherinlal/splitledger/MainActivity;->sendPick(Ljava/lang/String;Ljava/lang/String;)V

    return-void
.end method


# Every number saved against one contact, percent-encoded and comma-joined.
#
# Falls back to just the number the picker returned whenever it cannot do
# better -- no contact id, permission refused, query failed, nothing found.
# That fallback is the whole of the old behaviour, so denying the permission
# costs the chooser and nothing else.
.method private numbersFor(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;
    .registers 12

    if-nez p2, :cond_gotpicked

    const-string p2, ""

    :cond_gotpicked
    invoke-static {p2}, Landroid/net/Uri;->encode(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v0

    if-eqz p1, :cond_fallback

    invoke-virtual {p1}, Ljava/lang/String;->length()I
    move-result v1

    if-eqz v1, :cond_fallback

    :try_start_1
    invoke-virtual {p0}, Lcom/sherinlal/splitledger/MainActivity;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v2

    sget-object v3, Landroid/provider/ContactsContract$CommonDataKinds$Phone;->CONTENT_URI:Landroid/net/Uri;

    const/4 v1, 0x1

    new-array v4, v1, [Ljava/lang/String;

    const/4 v1, 0x0

    const-string v5, "data1"

    aput-object v5, v4, v1

    const-string v5, "contact_id=?"

    const/4 v1, 0x1

    new-array v6, v1, [Ljava/lang/String;

    const/4 v1, 0x0

    aput-object p1, v6, v1

    const/4 v7, 0x0

    invoke-virtual/range {v2 .. v7}, Landroid/content/ContentResolver;->query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;
    move-result-object v8

    if-eqz v8, :cond_fallback

    new-instance v1, Ljava/lang/StringBuilder;

    invoke-direct {v1}, Ljava/lang/StringBuilder;-><init>()V

    :goto_row
    invoke-interface {v8}, Landroid/database/Cursor;->moveToNext()Z
    move-result v2

    if-eqz v2, :cond_rowsdone

    const/4 v2, 0x0

    invoke-interface {v8, v2}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v3

    if-eqz v3, :goto_row

    invoke-virtual {v3}, Ljava/lang/String;->trim()Ljava/lang/String;
    move-result-object v3

    invoke-virtual {v3}, Ljava/lang/String;->length()I
    move-result v2

    if-eqz v2, :goto_row

    invoke-virtual {v1}, Ljava/lang/StringBuilder;->length()I
    move-result v2

    if-lez v2, :cond_nocomma

    const-string v2, ","

    invoke-virtual {v1, v2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    :cond_nocomma
    invoke-static {v3}, Landroid/net/Uri;->encode(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3

    invoke-virtual {v1, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    goto :goto_row

    :cond_rowsdone
    invoke-interface {v8}, Landroid/database/Cursor;->close()V

    invoke-virtual {v1}, Ljava/lang/StringBuilder;->length()I
    move-result v2

    if-lez v2, :cond_fallback

    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    :try_end_1
    .catch Ljava/lang/Exception; {:try_start_1 .. :try_end_1} :catch_1

    return-object v0

    :catch_1
    move-exception v1

    :cond_fallback
    return-object v0
.end method


# Hand the chosen contact to the page: the name, and every number saved against
# it as a comma-joined list. Both are percent-encoded -- the name here, the
# numbers already -- so quotes, backslashes and newlines in a contact name
# cannot break out of the JavaScript string literal.
.method private sendPick(Ljava/lang/String;Ljava/lang/String;)V
    .registers 6

    if-nez p1, :cond_a

    const-string p1, ""

    :cond_a
    if-nez p2, :cond_b

    const-string p2, ""

    :cond_b
    new-instance v0, Ljava/lang/StringBuilder;

    invoke-direct {v0}, Ljava/lang/StringBuilder;-><init>()V

    const-string v1, "javascript:if(window.__contactPicked)window.__contactPicked(\""

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-static {p1}, Landroid/net/Uri;->encode(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const-string v1, "\",\""

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    # p2 is already percent-encoded, comma-joined: encoding it again would turn
    # the separators into %2C and the page would read one long number
    invoke-virtual {v0, p2}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const-string v1, "\")"

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    iget-object v2, p0, Lcom/sherinlal/splitledger/MainActivity;->w:Landroid/webkit/WebView;

    if-eqz v2, :cond_done

    invoke-virtual {v0}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v1

    invoke-virtual {v2, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    :cond_done
    return-void
.end method


.method public onBackPressed()V
    .registers 3

    iget-object v0, p0, Lcom/sherinlal/splitledger/MainActivity;->w:Landroid/webkit/WebView;

    if-eqz v0, :exit

    invoke-virtual {v0}, Landroid/webkit/WebView;->canGoBack()Z
    move-result v1

    if-eqz v1, :exit

    invoke-virtual {v0}, Landroid/webkit/WebView;->goBack()V

    return-void

    :exit
    invoke-super {p0}, Landroid/app/Activity;->onBackPressed()V

    return-void
.end method
