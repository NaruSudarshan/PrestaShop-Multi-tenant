import os
import socket
import subprocess
import time
import requests
from flask import Flask, jsonify, send_from_directory, request

app = Flask(__name__, static_folder='static')
BASE_PORT = int(os.getenv('BASE_PORT', 8081))
TENANTS_DIR = os.getenv('TENANTS_DIR', 'tenants')
os.makedirs(TENANTS_DIR, exist_ok=True)

def get_next_port():
    port = BASE_PORT
    while True:
        with socket.socket() as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
        port += 1

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/create-store', methods=['POST'])
def create_store():
    body = request.get_json(force=True)
    custom_email = body.get("email")
    custom_password = body.get("password")

    existing = os.listdir(TENANTS_DIR)
    tenant = f"tenant{len(existing)+1}"
    port = get_next_port()
    path = os.path.join(TENANTS_DIR, tenant)
    os.makedirs(path, exist_ok=True)

    admin_email = custom_email
    admin_password = custom_password
    admin_folder = "admin"  # fallback

    compose = f"""
version: '3.9'
services:
  db:
    image: mysql:5.7
    container_name: {tenant}_db
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: prestashop
      MYSQL_USER: psuser
      MYSQL_PASSWORD: pspassword
    networks:
      - ps-net
    volumes:
      - db_data_{tenant}:/var/lib/mysql

  prestashop:
    image: prestashop/prestashop:8-apache
    container_name: {tenant}_shop
    restart: always
    depends_on:
      - db
    networks:
      - ps-net
    ports:
      - "{port}:80"
    environment:
      DB_SERVER: db
      DB_USER: psuser
      DB_PASSWD: pspassword
      PS_INSTALL_AUTO: '1'
      PS_DEV_MODE: '0'
      PS_HOST_MODE: '1'
      PS_ENABLE_SSL: '0'
      PS_HANDLE_DYNAMIC_DOMAIN: '0'
      PS_DOMAIN: localhost:{port}
      PS_LANGUAGE: en
      PS_COUNTRY: US
      PS_FOLDER_ADMIN: {admin_folder}
      PS_FOLDER_INSTALL: install
      ADMIN_MAIL: {admin_email}
      ADMIN_PASSWD: {admin_password}
    volumes:
      - ps_data_{tenant}:/var/www/html

volumes:
  db_data_{tenant}:
  ps_data_{tenant}:

networks:
  ps-net:
    driver: bridge
"""

    with open(f"{path}/docker-compose.yml", "w") as f:
        f.write(compose)

    subprocess.run([
        'sudo', 'docker-compose', '-f', f'{path}/docker-compose.yml', 'up', '-d'
    ], check=True)

    # Wait until the shop responds on the port
    shop_url = f"http://localhost:{port}"
    for _ in range(30):
        try:
            r = requests.get(shop_url, timeout=5)
            if r.status_code == 200 and 'presta' in r.text.lower():
                break
        except requests.RequestException:
            pass
        time.sleep(2)

    # Retry to find admin folder
    container_name = f"{tenant}_shop"
    admin_folder = "admin"  # fallback

    for _ in range(30):
        try:
            command = f"docker exec {container_name} sh -c \"basename $(find /var/www/html -maxdepth 1 -type d -name 'admin*' | head -n 1)\""
            admin_folder = subprocess.check_output(command, shell=True).decode().strip()
            if admin_folder.startswith("admin"):
                break
        except subprocess.CalledProcessError:
            pass
        time.sleep(2)
    else:
        print("⚠️ Failed to fetch admin folder. Using fallback.")

    admin_url = f"{shop_url}/{admin_folder}"
    return jsonify({
        'url': shop_url,
        'admin_url': admin_url,
        'admin_email': admin_email,
        'admin_password': admin_password
    })

if __name__ == '__main__':
    app.run('0.0.0.0', 5000)
