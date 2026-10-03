package android.content;
public class ClipData { public final android.net.Uri uri; ClipData(android.net.Uri u) { uri = u; }
  public static ClipData newRawUri(CharSequence label, android.net.Uri u) { return new ClipData(u); } }
