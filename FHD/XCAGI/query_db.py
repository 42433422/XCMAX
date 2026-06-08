import sqlite3
conn = sqlite3.connect('products.db')
cursor = conn.cursor()

print('=== Search 百木鼎 ===')
cursor.execute("SELECT id, name, model_number, specification, price, unit FROM products WHERE name LIKE '%百木鼎%' OR model_number LIKE '%百木鼎%'")
for row in cursor.fetchall():
    print(row)

print()
print('=== Search 306B ===')
cursor.execute("SELECT id, name, model_number, specification, price, unit FROM products WHERE name LIKE '%306B%' OR model_number LIKE '%306B%'")
for row in cursor.fetchall():
    print(row)

print()
print('=== Purchase Units (深圳) ===')
cursor.execute("SELECT id, unit_name, contact_person, contact_phone FROM purchase_units WHERE unit_name LIKE '%深圳%' LIMIT 10")
for row in cursor.fetchall():
    print(row)

print()
print('=== All products (limit 20) ===')
cursor.execute('SELECT id, name, model_number, specification, price, unit FROM products LIMIT 20')
for row in cursor.fetchall():
    print(row)

conn.close()