.class public Lcom/sherinlal/splitledger/MainActivity;
.super Landroid/app/Activity;
.implements Ljava/lang/Runnable;
.source "MainActivity.java"

# The whole app: one Activity hosting a WebView that loads assets/index.html.
#
# It declares NO permissions. The one native capability exposed to the page is
# pickContact(), which fires Android's own contact picker as a separate
# activity; the app never reads the address book itself, and only the single
# contact the user taps comes back (via a temporary URI grant in the result
# Intent). That is why READ_CONTACTS is not needed and not asked for.
#
# Runnable is implemented so pickContact() -- which the WebView calls on its
# own binder thread -- can hop to the UI thread without a second class.

.field private w:Landroid/webkit/WebView;


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
    # the single annotated method below
    const-string v1, "AndroidBridge"

    invoke-virtual {v0, p0, v1}, Landroid/webkit/WebView;->addJavascriptInterface(Ljava/lang/Object;Ljava/lang/String;)V

    invoke-virtual {p0, v0}, Lcom/sherinlal/splitledger/MainActivity;->setContentView(Landroid/view/View;)V

    const-string v1, "file:///android_asset/index.html"

    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    return-void
.end method


# Called from the WebView's binder thread. Hop to the UI thread to start the
# picker.
.method public pickContact()V
    .registers 1
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    invoke-virtual {p0, p0}, Lcom/sherinlal/splitledger/MainActivity;->runOnUiThread(Ljava/lang/Runnable;)V

    return-void
.end method


.method public run()V
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

    if-ltz v11, :cond_close

    invoke-interface {v10, v11}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v2

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
    invoke-direct {p0, v1, v2}, Lcom/sherinlal/splitledger/MainActivity;->sendPick(Ljava/lang/String;Ljava/lang/String;)V

    return-void
.end method


# Hand the chosen contact to the page. Both values are percent-encoded, so
# quotes, backslashes and newlines in a contact name cannot break out of the
# JavaScript string literal; the page decodes them.
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

    invoke-static {p2}, Landroid/net/Uri;->encode(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1

    invoke-virtual {v0, v1}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

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
