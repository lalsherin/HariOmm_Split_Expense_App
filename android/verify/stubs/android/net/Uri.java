package android.net;
public class Uri implements android.os.Parcelable {
  final String s; Uri(String s) { this.s = s; }
  public static Uri parse(String s) { return new Uri(s); }
  public String getLastPathSegment() { String t = s.replaceAll("/+$", ""); int i = t.lastIndexOf('/'); return i < 0 ? t : t.substring(i + 1); }
  public String toString() { return s; } }
