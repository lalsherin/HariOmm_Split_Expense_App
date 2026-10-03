package android.database;
import java.util.*;
public class MatrixCursor implements Cursor { public final String[] cols; public final List<Object[]> rows = new ArrayList<>();
  public MatrixCursor(String[] c) { cols = c; } public void addRow(Object[] r) { rows.add(r); } }
