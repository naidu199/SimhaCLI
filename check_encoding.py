data = open('bot/commands.py', 'rb').read()
non_ascii = [(i, chr(b)) for i, b in enumerate(data) if b > 127]
print('Non-ASCII bytes (first 30):', non_ascii[:30])
