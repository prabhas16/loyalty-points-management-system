import ast
from pathlib import Path
ast.parse(Path("app.py").read_text(encoding="utf-8"))
print("Python syntax check passed.")
print("Install requirements, configure .env, create the MySQL database, then run: python app.py")
