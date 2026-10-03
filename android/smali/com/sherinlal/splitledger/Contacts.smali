.class public final Lcom/sherinlal/splitledger/Contacts;
.super Ljava/lang/Object;
.source "Contacts.java"

# Every phone number in the address book, for the app's own multi-select
# contact picker. Android's picker (ACTION_PICK) returns one contact per
# opening and closes; choosing ten people meant opening it ten times.
#
# Uses READ_CONTACTS, which the app already asks for -- at the moment Contacts
# is tapped, never at launch. Nothing is sent anywhere: the list goes to the
# page in this process, and only the people chosen become group members.
#
# Kept in its own class on purpose. MainActivity calls it inside a catch-all,
# so if this ever fails on some phone -- a contacts provider that throws, or
# anything the verifier dislikes -- the app falls back to the one-at-a-time
# picker instead of failing to start.
#
# Returns, one row per number, newline-separated:
#     <name>,<number>,<contact id>
# each field percent-encoded with Uri.encode, which also encodes ',' and '\n',
# so a contact name can never break the format. "!" means permission is not
# granted, "?" that the query failed.


.method public static list(Landroid/content/Context;)Ljava/lang/String;
    # p0 (the Context) is v11; every local below stays in v0..v10
    .registers 12

    const-string v0, "android.permission.READ_CONTACTS"

    invoke-virtual {p0, v0}, Landroid/content/Context;->checkSelfPermission(Ljava/lang/String;)I
    move-result v0

    if-eqz v0, :granted

    const-string v0, "!"

    return-object v0

    :granted
    :try_start_0
    invoke-virtual {p0}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;
    move-result-object v1

    sget-object v2, Landroid/provider/ContactsContract$CommonDataKinds$Phone;->CONTENT_URI:Landroid/net/Uri;

    const/4 v0, 0x3

    new-array v3, v0, [Ljava/lang/String;

    const/4 v0, 0x0

    const-string v4, "display_name"

    aput-object v4, v3, v0

    const/4 v0, 0x1

    const-string v4, "data1"

    aput-object v4, v3, v0

    const/4 v0, 0x2

    const-string v4, "contact_id"

    aput-object v4, v3, v0

    const/4 v4, 0x0

    const/4 v5, 0x0

    const/4 v6, 0x0

    invoke-virtual/range {v1 .. v6}, Landroid/content/ContentResolver;->query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;
    move-result-object v7

    if-nez v7, :have_cursor

    const-string v0, "?"

    return-object v0

    :have_cursor
    new-instance v8, Ljava/lang/StringBuilder;

    invoke-direct {v8}, Ljava/lang/StringBuilder;-><init>()V

    :next_row
    invoke-interface {v7}, Landroid/database/Cursor;->moveToNext()Z
    move-result v0

    if-eqz v0, :rows_done

    const/4 v0, 0x0

    invoke-interface {v7, v0}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v9

    const/4 v0, 0x1

    invoke-interface {v7, v0}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v10

    # a row with no number is no use to anyone here
    if-eqz v10, :next_row

    invoke-virtual {v8}, Ljava/lang/StringBuilder;->length()I
    move-result v0

    if-eqz v0, :first_row

    const-string v0, "\n"

    invoke-virtual {v8, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    :first_row
    if-nez v9, :has_name

    const-string v9, ""

    :has_name
    invoke-static {v9}, Landroid/net/Uri;->encode(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v9

    invoke-virtual {v8, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const-string v0, ","

    invoke-virtual {v8, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-static {v10}, Landroid/net/Uri;->encode(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v10

    invoke-virtual {v8, v10}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v8, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    const/4 v0, 0x2

    invoke-interface {v7, v0}, Landroid/database/Cursor;->getString(I)Ljava/lang/String;
    move-result-object v9

    if-nez v9, :has_cid

    const-string v9, ""

    :has_cid
    invoke-static {v9}, Landroid/net/Uri;->encode(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v9

    invoke-virtual {v8, v9}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    goto :next_row

    :rows_done
    invoke-interface {v7}, Landroid/database/Cursor;->close()V

    invoke-virtual {v8}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;
    move-result-object v0
    :try_end_0
    .catch Ljava/lang/Exception; {:try_start_0 .. :try_end_0} :catch_0

    return-object v0

    :catch_0
    move-exception v0

    const-string v0, "?"

    return-object v0
.end method
