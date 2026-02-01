import secrets
import random

if not hasattr(secrets, 'choice'):
    secrets.choice = random.SystemRandom().choice
    print("✅ Применен патч: secrets.choice добавлен")