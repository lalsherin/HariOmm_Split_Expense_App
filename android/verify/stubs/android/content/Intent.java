package android.content;
import java.util.*;
public class Intent { public String action, type; public Map<String,Object> extras = new HashMap<>(); public int flags; public ClipData clip;
  public Intent(String a) { action = a; }
  public Intent setType(String t) { type = t; return this; }
  public Intent putExtra(String k, android.os.Parcelable v) { extras.put(k, v); return this; }
  public Intent putExtra(String k, String v) { extras.put(k, v); return this; }
  public Intent addFlags(int f) { flags |= f; return this; }
  public void setClipData(ClipData c) { clip = c; }
  public static Intent createChooser(Intent target, CharSequence title) { Intent c = new Intent("CHOOSER"); c.extras.put("target", target); c.extras.put("title", String.valueOf(title)); return c; } }
