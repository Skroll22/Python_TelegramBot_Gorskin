import sys
import secrets

print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"Has secrets.choice: {hasattr(secrets, 'choice')}")
print(f"secrets module location: {secrets.__file__}")