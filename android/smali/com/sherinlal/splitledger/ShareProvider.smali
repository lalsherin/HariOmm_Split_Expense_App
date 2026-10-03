.class public final Lcom/sherinlal/splitledger/ShareProvider;
.super Landroid/content/ContentProvider;
.source "ShareProvider.java"

# Hands ONE file to the app the person picks in the share sheet: the share
# card the page just drew, at <cache>/share/split-buddy-card.png.
#
# This is what androidx's FileProvider does, written out because this build
# has no Gradle and no androidx. Declared in the manifest with
# exported="false" and grantUriPermissions="true": no app can read it unless
# Split Buddy grants a temporary read permission on that one URI, which it
# does only when sharing. Read-only; any other name is "not found", so a path
# like ../../ can never reach anything else.
#
# Android creates this class when the app process starts, so it is kept as
# small and plain as possible.


.method public constructor <init>()V
    .registers 1

    invoke-direct {p0}, Landroid/content/ContentProvider;-><init>()V

    return-void
.end method


.method public onCreate()Z
    .registers 2

    const/4 v0, 0x1

    return v0
.end method


.method public getType(Landroid/net/Uri;)Ljava/lang/String;
    .registers 3

    const-string v0, "image/png"

    return-object v0
.end method


# The shared file for this URI, or null for anything else.
.method private fileFor(Landroid/net/Uri;)Ljava/io/File;
    .registers 6

    if-eqz p1, :none

    invoke-virtual {p1}, Landroid/net/Uri;->getLastPathSegment()Ljava/lang/String;
    move-result-object v0

    const-string v1, "split-buddy-card.png"

    invoke-virtual {v1, v0}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z
    move-result v2

    if-eqz v2, :none

    invoke-virtual {p0}, Landroid/content/ContentProvider;->getContext()Landroid/content/Context;
    move-result-object v0

    if-eqz v0, :none

    invoke-virtual {v0}, Landroid/content/Context;->getCacheDir()Ljava/io/File;
    move-result-object v0

    new-instance v2, Ljava/io/File;

    const-string v3, "share"

    invoke-direct {v2, v0, v3}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    new-instance v0, Ljava/io/File;

    invoke-direct {v0, v2, v1}, Ljava/io/File;-><init>(Ljava/io/File;Ljava/lang/String;)V

    return-object v0

    :none
    const/4 v0, 0x0

    return-object v0
.end method


.method public openFile(Landroid/net/Uri;Ljava/lang/String;)Landroid/os/ParcelFileDescriptor;
    .registers 6
    .annotation system Ldalvik/annotation/Throws;
        value = {
            Ljava/io/FileNotFoundException;
        }
    .end annotation

    invoke-direct {p0, p1}, Lcom/sherinlal/splitledger/ShareProvider;->fileFor(Landroid/net/Uri;)Ljava/io/File;
    move-result-object v0

    if-eqz v0, :missing

    invoke-virtual {v0}, Ljava/io/File;->exists()Z
    move-result v1

    if-eqz v1, :missing

    # ParcelFileDescriptor.MODE_READ_ONLY
    const/high16 v1, 0x10000000

    invoke-static {v0, v1}, Landroid/os/ParcelFileDescriptor;->open(Ljava/io/File;I)Landroid/os/ParcelFileDescriptor;
    move-result-object v0

    return-object v0

    :missing
    new-instance v0, Ljava/io/FileNotFoundException;

    const-string v1, "not shared"

    invoke-direct {v0, v1}, Ljava/io/FileNotFoundException;-><init>(Ljava/lang/String;)V

    throw v0
.end method


# Name and size, which Gmail, WhatsApp and others ask for before reading.
.method public query(Landroid/net/Uri;[Ljava/lang/String;Ljava/lang/String;[Ljava/lang/String;Ljava/lang/String;)Landroid/database/Cursor;
    .registers 11

    invoke-direct {p0, p1}, Lcom/sherinlal/splitledger/ShareProvider;->fileFor(Landroid/net/Uri;)Ljava/io/File;
    move-result-object v0

    if-eqz v0, :none

    const/4 v1, 0x2

    new-array v2, v1, [Ljava/lang/String;

    const/4 v1, 0x0

    const-string v3, "_display_name"

    aput-object v3, v2, v1

    const/4 v1, 0x1

    const-string v3, "_size"

    aput-object v3, v2, v1

    new-instance v1, Landroid/database/MatrixCursor;

    invoke-direct {v1, v2}, Landroid/database/MatrixCursor;-><init>([Ljava/lang/String;)V

    const/4 v2, 0x2

    new-array v2, v2, [Ljava/lang/Object;

    const/4 v3, 0x0

    const-string v4, "split-buddy-card.png"

    aput-object v4, v2, v3

    invoke-virtual {v0}, Ljava/io/File;->length()J
    move-result-wide v3

    invoke-static {v3, v4}, Ljava/lang/Long;->valueOf(J)Ljava/lang/Long;
    move-result-object v3

    const/4 v4, 0x1

    aput-object v3, v2, v4

    invoke-virtual {v1, v2}, Landroid/database/MatrixCursor;->addRow([Ljava/lang/Object;)V

    return-object v1

    :none
    const/4 v0, 0x0

    return-object v0
.end method


# Read-only: nothing can be written through this provider.
.method public insert(Landroid/net/Uri;Landroid/content/ContentValues;)Landroid/net/Uri;
    .registers 4

    const/4 v0, 0x0

    return-object v0
.end method


.method public delete(Landroid/net/Uri;Ljava/lang/String;[Ljava/lang/String;)I
    .registers 5

    const/4 v0, 0x0

    return v0
.end method


.method public update(Landroid/net/Uri;Landroid/content/ContentValues;Ljava/lang/String;[Ljava/lang/String;)I
    .registers 6

    const/4 v0, 0x0

    return v0
.end method
