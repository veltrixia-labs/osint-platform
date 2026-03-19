import ast
import sys

filepath = 'alembic/versions/546c64d1a7fb_add_missing_alert_log_columns.py'
try:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
except FileNotFoundError:
    print('Error: Migration file not found.')
    sys.exit(1)

# Remove all imports of sqlite dialect just in case
content = content.replace("from sqlalchemy.dialects import sqlite", "")

class AlembicCleaner(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Call):
            func = getattr(node.value.func, 'attr', '')
            if func in ('alter_column', 'drop_constraint'):
                if func == 'drop_constraint':
                    if hasattr(node.value.args[0], 'value') and node.value.args[0].value is None:
                        return None # Remove drop_constraint(None, ...)
                    if hasattr(node.value.args[0], 'id') and node.value.args[0].id == 'None':
                        return None
                return None # Remove alter_column
        return node

try:
    tree = ast.parse(content)
except SyntaxError as e:
    print(f'SyntaxError parsing migration file: {e}')
    sys.exit(1)
    
cleaner = AlembicCleaner()
tree = cleaner.visit(tree)
new_content = ast.unparse(tree)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content)
    
print('Migration cleaned successfully.')
