import os, collections
root = r'c:\Users\rgcon\.git\elite-powerplay-app'
exts = collections.Counter()
lines = collections.Counter()
for dirpath, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in ('.git','node_modules','__pycache__')]
    for f in files:
        if f.startswith(('_debug_','_clear_','_check_','_peek_','_probe_','_scan_','_test_')):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in ('.py','.tsx','.ts','.yml','.yaml','.json','.css','.html'):
            fp = os.path.join(dirpath, f)
            try:
                with open(fp, encoding='utf-8', errors='ignore') as fh:
                    lc = sum(1 for _ in fh)
                exts[ext] += 1
                lines[ext] += lc
            except:
                pass
print("Ext       Files    Lines")
print("-" * 30)
total_f = total_l = 0
for ext in sorted(exts, key=lambda e: -lines[e]):
    print(f"{ext:<8} {exts[ext]:>6} {lines[ext]:>8}")
    total_f += exts[ext]
    total_l += lines[ext]
print("-" * 30)
print(f"TOTAL    {total_f:>6} {total_l:>8}")