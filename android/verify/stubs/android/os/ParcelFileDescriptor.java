package android.os;
public class ParcelFileDescriptor { public final java.io.File file; public final int mode;
  ParcelFileDescriptor(java.io.File f, int m) { file = f; mode = m; }
  public static ParcelFileDescriptor open(java.io.File f, int mode) throws java.io.FileNotFoundException {
    if (!f.exists()) throw new java.io.FileNotFoundException(); return new ParcelFileDescriptor(f, mode); } }
