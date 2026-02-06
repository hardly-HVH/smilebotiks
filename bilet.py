#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==================== SMILE PARTY BOT - FINAL VERSION ====================

import warnings
warnings.filterwarnings("ignore", message="If 'per_message=False'")

import json
import re
import logging
import asyncio
import sqlite3
import random
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import os
from contextlib import closing
import traceback

# ========== НАСТРОЙКИ БОТА ==========
BOT_TOKEN = "8433063885:AAFPT2fYk6HQB1gt-x2kxqaIaSJE9U3tQdM"
ADMIN_IDS = [7978634199, 1037472337]
PROMOTER_IDS = [7283583682, 6179688188, 8387903981, 8041100755, 1380285963, 1991277474, 8175354320, 6470777539, 8470198654, 7283630429, 8396505232, 8176926325, 8566108065, 7978634199]

# ID каналов и чатов
CLOSED_ORDERS_CHANNEL_ID = -1003780187586
REFUND_ORDERS_CHANNEL_ID = -1003735636374
PROMOTERS_CHAT_ID = -1003105307057
LISTS_CHANNEL_ID = -1003661551964
LOGS_CHANNEL_ID = -1003610531501

# Файл базы данных
DB_FILE = "smile_party_bot.db"

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== ИМПОРТ ТЕЛЕГРАМ МОДУЛЕЙ ==========
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    ApplicationBuilder
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError

# ========== ФУНКЦИИ ДЛЯ ЛОГИРОВАНИЯ ==========
async def send_log_to_channel(context: ContextTypes.DEFAULT_TYPE, message: str, level: str = "INFO"):
    """Отправляет лог в канал"""
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_message = f"[{timestamp}] [{level}] {message}"
        
        if len(log_message) > 4000:
            log_message = log_message[:4000] + "..."
        
        await context.bot.send_message(
            chat_id=LOGS_CHANNEL_ID,
            text=f"`{log_message}`",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"Ошибка отправки лога в канал: {e}")

# ========== ФУНКЦИИ ДЛЯ ГЕНЕРАЦИИ УНИКАЛЬНЫХ КОДОВ ==========
def generate_unique_code(length: int = 6) -> str:
    """Генерирует уникальный код для заказа в формате #KA123456"""
    characters = string.digits
    while True:
        numbers = ''.join(random.choices(characters, k=length))
        code = f"#KA{numbers}"
        if not db.get_order_by_code(code):
            return code

def format_code_for_display(code: str) -> str:
    """Форматирует код для отображения"""
    return code

# ========== КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ SQLite ==========
class Database:
    """Класс для работы с SQLite базой данных"""
    
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file
        self.init_database()
    
    def get_connection(self):
        """Получить соединение с базой данных"""
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Инициализация таблиц базы данных"""
        with closing(self.get_connection()) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS event_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    setting_key VARCHAR(50) UNIQUE NOT NULL,
                    setting_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id BIGINT UNIQUE NOT NULL,
                    username VARCHAR(100),
                    first_name VARCHAR(100),
                    last_name VARCHAR(100),
                    role VARCHAR(20) DEFAULT 'user',
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    notified_about_restart BOOLEAN DEFAULT FALSE
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id VARCHAR(20) UNIQUE NOT NULL,
                    order_code VARCHAR(20) UNIQUE NOT NULL,
                    user_id BIGINT NOT NULL,
                    username VARCHAR(100),
                    user_name VARCHAR(200) NOT NULL,
                    user_email VARCHAR(100) NOT NULL,
                    group_size INTEGER NOT NULL,
                    ticket_type VARCHAR(10) DEFAULT 'standard',
                    total_amount INTEGER NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    assigned_promoter VARCHAR(100),
                    closed_by VARCHAR(100),
                    closed_at TIMESTAMP,
                    notified_promoters BOOLEAN DEFAULT FALSE
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id VARCHAR(20) NOT NULL,
                    order_code VARCHAR(20) NOT NULL,
                    guest_number INTEGER NOT NULL,
                    full_name VARCHAR(200) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
                    UNIQUE(order_id, guest_number)
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_code ON orders(order_code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_guests_order_id ON guests(order_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_guests_order_code ON guests(order_code)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON bot_users(role)")
            
            conn.commit()
            logger.info("✅ Таблицы SQLite базы данных инициализированы")
    
    def add_column_if_not_exists(self, table_name: str, column_name: str, column_type: str):
        """Добавить колонку в таблицу если она не существует"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if column_name not in column_names:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                    conn.commit()
                    logger.info(f"✅ Добавлена колонка {column_name} в таблицу {table_name}")
                    return True
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка добавления колонки {column_name}: {e}")
            return False
    
    def check_and_fix_database(self):
        """Проверить и исправить структуру базы данных"""
        logger.info("🔧 Проверка структуры базы данных...")
        
        self.add_column_if_not_exists("orders", "ticket_type", "VARCHAR(10) DEFAULT 'standard'")
        self.add_column_if_not_exists("bot_users", "notified_about_restart", "BOOLEAN DEFAULT FALSE")
        self.add_column_if_not_exists("orders", "notified_promoters", "BOOLEAN DEFAULT FALSE")
        
        logger.info("✅ Структура базы данных проверена")
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Получить значение настройки"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT setting_value FROM event_settings WHERE setting_key = ?", (key,))
                result = cursor.fetchone()
                
                if result:
                    try:
                        return json.loads(result[0])
                    except:
                        return result[0]
                return default
        except Exception as e:
            logger.error(f"❌ Ошибка получения настройки {key}: {e}")
            return default
    
    def set_setting(self, key: str, value: Any) -> bool:
        """Установить значение настройки"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                
                if isinstance(value, (dict, list)):
                    value_json = json.dumps(value, ensure_ascii=False)
                else:
                    value_json = str(value)
                
                cursor.execute("""
                    INSERT OR REPLACE INTO event_settings (setting_key, setting_value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                """, (key, value_json))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка установки настройки {key}: {e}")
            return False
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Добавить/обновить пользователя"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                
                role = self._get_user_role(user_id)
                
                cursor.execute("""
                    INSERT OR REPLACE INTO bot_users 
                    (user_id, username, first_name, last_name, role, last_active, is_active)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, TRUE)
                """, (user_id, username, first_name, last_name, role))
                
                conn.commit()
                logger.info(f"✅ Пользователь {user_id} добавлен/обновлен")
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления пользователя {user_id}: {e}")
            return False
    
    def mark_user_notified(self, user_id: int):
        """Пометить пользователя как уведомленного о перезапуске"""
        try:
            self.add_column_if_not_exists("bot_users", "notified_about_restart", "BOOLEAN DEFAULT FALSE")
            
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE bot_users 
                    SET notified_about_restart = TRUE 
                    WHERE user_id = ?
                """, (user_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статуса уведомления для пользователя {user_id}: {e}")
            return False
    
    def reset_notification_status(self):
        """Сбросить статус уведомлений для всех пользователей"""
        try:
            self.add_column_if_not_exists("bot_users", "notified_about_restart", "BOOLEAN DEFAULT FALSE")
            
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE bot_users SET notified_about_restart = FALSE")
                conn.commit()
                logger.info("✅ Статус уведомлений сброшен для всех пользователей")
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка сброса статуса уведомлений: {e}")
            return False
    
    def get_users_to_notify(self) -> List[Dict]:
        """Получить пользователей для уведомления о перезапуске"""
        try:
            self.add_column_if_not_exists("bot_users", "notified_about_restart", "BOOLEAN DEFAULT FALSE")
            
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM bot_users 
                    WHERE is_active = TRUE 
                    AND notified_about_restart = FALSE
                """)
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка получения пользователей для уведомления: {e}")
            return []
    
    def _get_user_role(self, user_id: int) -> str:
        """Определить роль пользователя"""
        if user_id in ADMIN_IDS:
            return "admin"
        elif user_id in PROMOTER_IDS:
            return "promoter"
        else:
            return "user"
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        """Получить информацию о пользователе"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM bot_users WHERE user_id = ?", (user_id,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения пользователя {user_id}: {e}")
            return None
    
    def get_all_users(self) -> List[Dict]:
        """Получить всех пользователей"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM bot_users WHERE is_active = TRUE")
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка получения всех пользователей: {e}")
            return []
    
    def get_promoters(self) -> List[Dict]:
        """Получить всех промоутеров"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM bot_users WHERE role = 'promoter' AND is_active = TRUE")
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка получения промоутеров: {e}")
            return []
    
    def create_order(self, user_id: int, username: str, user_name: str, 
                    user_email: str, group_size: int, ticket_type: str, total_amount: int) -> Dict:
        """Создать новый заказ с уникальным кодом"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                
                self.add_column_if_not_exists("orders", "ticket_type", "VARCHAR(10) DEFAULT 'standard'")
                
                cursor.execute("SELECT COALESCE(MAX(CAST(SUBSTR(order_id, 3) AS INTEGER)), 999) FROM orders")
                max_id = cursor.fetchone()[0] or 999
                order_id = f"SP{max_id + 1}"
                
                order_code = generate_unique_code()
                
                cursor.execute("""
                    INSERT INTO orders 
                    (order_id, order_code, user_id, username, user_name, user_email, 
                     group_size, ticket_type, total_amount, status, notified_promoters)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', FALSE)
                """, (order_id, order_code, user_id, username, user_name, user_email, 
                      group_size, ticket_type, total_amount))
                
                conn.commit()
                logger.info(f"✅ Заказ {order_id} создан, код: {order_code}, тип: {ticket_type}")
                
                return {
                    'order_id': order_id,
                    'order_code': order_code,
                    'user_id': user_id,
                    'username': username,
                    'user_name': user_name,
                    'user_email': user_email,
                    'group_size': group_size,
                    'ticket_type': ticket_type,
                    'total_amount': total_amount,
                    'status': 'active'
                }
        except Exception as e:
            logger.error(f"❌ Ошибка создания заказа: {e}")
            return None
    
    def mark_order_notified(self, order_id: str):
        """Пометить заказ как уведомленный для промоутеров"""
        try:
            self.add_column_if_not_exists("orders", "notified_promoters", "BOOLEAN DEFAULT FALSE")
            
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE orders 
                    SET notified_promoters = TRUE 
                    WHERE order_id = ?
                """, (order_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статуса уведомления для заказа {order_id}: {e}")
            return False
    
    def get_unnotified_orders(self) -> List[Dict]:
        """Получить заказы, по которым не отправлялись уведомления промоутерам"""
        try:
            self.add_column_if_not_exists("orders", "notified_promoters", "BOOLEAN DEFAULT FALSE")
            
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM orders 
                    WHERE status = 'active' 
                    AND notified_promoters = FALSE
                    ORDER BY created_at
                """)
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка получения неуведомленных заказов: {e}")
            return []
    
    def add_guests_to_order(self, order_id: str, order_code: str, guests: List[str]):
        """Добавить гостей к заказу"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                
                for i, guest_name in enumerate(guests, 1):
                    cursor.execute("""
                        INSERT INTO guests (order_id, order_code, guest_number, full_name)
                        VALUES (?, ?, ?, ?)
                    """, (order_id, order_code, i, guest_name.strip()))
                
                conn.commit()
                logger.info(f"✅ Добавлено {len(guests)} гостей к заказу {order_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка добавления гостей к заказу {order_id}: {e}")
            return False
    
    def get_order(self, order_id: str) -> Optional[Dict]:
        """Получить заказ по ID"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения заказа {order_id}: {e}")
            return None
    
    def get_order_by_code(self, order_code: str) -> Optional[Dict]:
        """Получить заказ по коду"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM orders WHERE order_code = ?", (order_code,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения заказа по коду {order_code}: {e}")
            return None
    
    def get_user_orders(self, user_id: int) -> List[Dict]:
        """Получить заказы пользователя"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка получения заказов пользователя {user_id}: {e}")
            return []
    
    def get_orders_by_status(self, status: str) -> List[Dict]:
        """Получить заказы по статусу"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM orders WHERE status = ? ORDER BY created_at", (status,))
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка получения заказов со статусом {status}: {e}")
            return []
    
    def update_order_status(self, order_id: str, status: str, promoter_username: str = None) -> bool:
        """Обновить статус заказа"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                
                if status in ["closed", "refunded"]:
                    cursor.execute("""
                        UPDATE orders 
                        SET status = ?, closed_by = ?, closed_at = CURRENT_TIMESTAMP
                        WHERE order_id = ?
                    """, (status, promoter_username, order_id))
                elif status in ["active", "deferred"]:
                    cursor.execute("""
                        UPDATE orders 
                        SET status = ?, assigned_promoter = ?
                        WHERE order_id = ?
                    """, (status, promoter_username, order_id))
                else:
                    cursor.execute("""
                        UPDATE orders 
                        SET status = ?
                        WHERE order_id = ?
                    """, (status, order_id))
                
                conn.commit()
                logger.info(f"✅ Статус заказа {order_id} изменен на {status}")
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статуса заказа {order_id}: {e}")
            return False
    
    def get_order_guests(self, order_id: str) -> List[Dict]:
        """Получить гостей заказа"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM guests WHERE order_id = ? ORDER BY guest_number", (order_id,))
                results = cursor.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Ошибка получения гостей заказа {order_id}: {e}")
            return []
    
    def get_all_guests_count(self) -> int:
        """Получить общее количество гостей"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM guests")
                count = cursor.fetchone()[0]
                return count
        except Exception as e:
            logger.error(f"❌ Ошибка получения общего количества гостей: {e}")
            return 0
    
    def reset_guests_count(self) -> bool:
        """Сбросить счетчик гостей (удалить всех гостей)"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM guests")
                conn.commit()
                logger.info("✅ Счетчик гостей сброшен")
                return True
        except Exception as e:
            logger.error(f"❌ Ошибка сброса счетчика гостей: {e}")
            return False
    
    def get_statistics(self) -> Dict:
        """Получить статистику"""
        try:
            with closing(self.get_connection()) as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM orders")
                total_orders = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'active'")
                active_orders = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'deferred'")
                deferred_orders = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'closed'")
                closed_orders = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'refunded'")
                refunded_orders = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE status = 'closed'")
                revenue = cursor.fetchone()[0] or 0
                
                total_guests = self.get_all_guests_count()
                
                cursor.execute("SELECT COUNT(*) FROM orders WHERE ticket_type = 'vip' AND status = 'closed'")
                vip_tickets = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COUNT(*) FROM orders WHERE ticket_type = 'standard' AND status = 'closed'")
                standard_tickets = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE ticket_type = 'vip' AND status = 'closed'")
                vip_revenue = cursor.fetchone()[0] or 0
                
                cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE ticket_type = 'standard' AND status = 'closed'")
                standard_revenue = cursor.fetchone()[0] or 0
                
                return {
                    "total_orders": total_orders,
                    "active_orders": active_orders,
                    "deferred_orders": deferred_orders,
                    "closed_orders": closed_orders,
                    "refunded_orders": refunded_orders,
                    "revenue": revenue,
                    "total_guests": total_guests,
                    "vip_tickets": vip_tickets,
                    "standard_tickets": standard_tickets,
                    "vip_revenue": vip_revenue,
                    "standard_revenue": standard_revenue
                }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return {}

# ========== КЛАСС ДЛЯ ХРАНЕНИЯ НАСТРОЕК ==========
class EventSettings:
    """Класс для хранения и управления настройками мероприятия"""
    
    DEFAULT_SETTINGS = {
        "event_name": "SMILE PARTY 🎉",
        "event_date": "25 декабря 2024",
        "event_time": "20:00 - 06:00",
        "event_address": "Москва, ул. Праздничная, 17 (м. Радостная)",
        "event_age_limit": "18+",
        "contact_telegram": "@smile_party",
        "price_standard": 450,
        "price_group": 350,
        "price_vip": 650,
        "group_threshold": 5,
        "description": "Самое громкое мероприятие сезона! Топовые DJ-сеты, live-выступления, конкурсы с призами.",
        "event_info_text": "🏢 *Информация о мероприятии*\n\n*🎉 Название:* SMILE PARTY 🎉\n*📍 Адрес:* Москва, ул. Праздничная, 17 (м. Радостная)\n*📅 Дата:* 25 декабря 2024\n*⏰ Время:* 20:00 - 06:00\n*🎭 Возраст:* 18+\n*📱 Telegram:* @smile_party\n\n*📝 Описание:*\nСамое громкое мероприятие сезона! Топовые DJ-сеты, live-выступления, конкурсы с призами."
    }
    
    def __init__(self, db: Database):
        self.db = db
        self._load_defaults()
    
    def _load_defaults(self):
        """Загрузить настройки по умолчанию в базу данных"""
        for key, value in self.DEFAULT_SETTINGS.items():
            current = self.db.get_setting(key)
            if current is None:
                self.db.set_setting(key, value)
    
    def get_all_settings(self) -> Dict:
        """Получить все настройки"""
        settings = {}
        for key in self.DEFAULT_SETTINGS.keys():
            value = self.db.get_setting(key)
            if value is not None:
                settings[key] = value
            else:
                settings[key] = self.DEFAULT_SETTINGS[key]
        return settings
    
    def get_price_standard(self) -> int:
        """Получить стандартную цену"""
        return self.db.get_setting("price_standard", 450)
    
    def get_price_group(self) -> int:
        """Получить групповую цену"""
        return self.db.get_setting("price_group", 350)
    
    def get_price_vip(self) -> int:
        """Получить VIP цену"""
        return self.db.get_setting("price_vip", 650)
    
    def get_group_threshold(self) -> int:
        """Получить порог для групповой цены"""
        return self.db.get_setting("group_threshold", 5)
    
    def calculate_price(self, group_size: int, ticket_type: str = "standard") -> int:
        """Рассчитать стоимость"""
        if ticket_type == "vip":
            return group_size * self.get_price_vip()
        elif group_size >= self.get_group_threshold():
            return group_size * self.get_price_group()
        else:
            return group_size * self.get_price_standard()
    
    def update_setting(self, key: str, value: Any) -> bool:
        """Обновить настройку"""
        if key in self.DEFAULT_SETTINGS:
            return self.db.set_setting(key, value)
        return False
    
    def reset_to_defaults(self) -> bool:
        """Сбросить настройки к значениям по умолчанию"""
        success = True
        for key, value in self.DEFAULT_SETTINGS.items():
            if not self.db.set_setting(key, value):
                success = False
        return success

# ========== ИНИЦИАЛИЗАЦИЯ ==========
db = Database(DB_FILE)
db.check_and_fix_database()
event_settings = EventSettings(db)

# Состояния
(
    ROLE_SELECTION,
    MAIN_MENU,
    BUY_TICKET_TYPE,
    BUY_NAME,
    BUY_EMAIL,
    BUY_GUESTS,
    BUY_CONFIRM,
    ADMIN_MENU,
    PROMOTER_MENU,
    ADMIN_EDIT,
    ADMIN_EDIT_TEXT,
    PROMOTER_VIEW_ORDER,
    PROMOTER_DEFERRED,
    ADMIN_RESET_STATS
) = range(14)

# ========== ПОМОЩНИКИ ==========
def get_user_role(user_id: int) -> str:
    """Определить роль пользователя"""
    if user_id in ADMIN_IDS:
        return "admin"
    elif user_id in PROMOTER_IDS:
        return "promoter"
    else:
        return "user"

def escape_markdown(text: str) -> str:
    """Экранирует специальные символы Markdown V2"""
    if not text:
        return ""
    
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    
    result = ''
    for char in text:
        if char in escape_chars:
            result += '\\' + char
        else:
            result += char
    
    return result

def is_valid_email(email: str) -> bool:
    """Проверяет валидность email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

async def send_channel_notification(context: ContextTypes.DEFAULT_TYPE, order: Dict, promoter_username: str, action: str):
    """Отправить уведомление в канал с уникальным кодом"""
    try:
        formatted_code = format_code_for_display(order['order_code'])
        
        if action == "closed":
            channel_id = CLOSED_ORDERS_CHANNEL_ID
            closed_time = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            
            ticket_type_text = "VIP 🎩" if order.get('ticket_type') == 'vip' else "Обычный 🎟"
            
            text = (
                "✅ *Заявка успешно обработана*\n\n"
                f"*Уникальный код:* `{order['order_code']}`\n"
                f"*Тип билета:* {ticket_type_text}\n"
                f"*ID заявки:* #{order['order_id']}\n"
                f"*Закрыл заявку:* @{escape_markdown(promoter_username)}\n"
                f"*Контактное лицо:* {escape_markdown(str(order['user_name']))}\n"
                f"*Telegram:* @{escape_markdown(str(order['username'] or 'без username'))}\n"
                f"*Email:* {escape_markdown(str(order['user_email']))}\n"
                f"*Дата закрытия:* {closed_time}\n"
                f"*Количество гостей:* {order['group_size']}\n"
                f"*Сумма:* {order['total_amount']} ₽"
            )
        elif action == "refunded":
            channel_id = REFUND_ORDERS_CHANNEL_ID
            closed_time = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            
            ticket_type_text = "VIP 🎩" if order.get('ticket_type') == 'vip' else "Обычный 🎟"
            
            text = (
                "❌ *Возврат заявки*\n\n"
                f"*Уникальный код:* `{order['order_code']}`\n"
                f"*Тип билета:* {ticket_type_text}\n"
                f"*ID заявки:* #{order['order_id']}\n"
                f"*Промоутер:* @{escape_markdown(promoter_username)}\n"
                f"*Контактное лицо:* {escape_markdown(str(order['user_name']))}\n"
                f"*Telegram:* @{escape_markdown(str(order['username'] or 'без username'))}\n"
                f"*Email:* {escape_markdown(str(order['user_email']))}\n"
                f"*Дата возврата:* {closed_time}\n"
                f"*Количество гостей:* {order['group_size']}\n"
                f"*Сумма:* {order['total_amount']} ₽"
            )
        else:
            return
        
        await context.bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Уведомление отправлено в канал для заказа #{order['order_id']}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления в канал: {e}")

async def send_to_lists_channel(context: ContextTypes.DEFAULT_TYPE, order: Dict, promoter_username: str):
    """Отправить информацию в канал со списками"""
    try:
        guests = db.get_order_guests(order['order_id'])
        closed_time = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        
        if not guests:
            return
        
        for guest in guests:
            guest_name = guest['full_name']
            
            name_parts = guest_name.strip().split()
            if len(name_parts) >= 2:
                last_name = name_parts[0]
                first_name = ' '.join(name_parts[1:])
            else:
                last_name = ""
                first_name = guest_name
            
            formatted_code = format_code_for_display(order['order_code'])
            
            ticket_type_text = "VIP 🎩" if order.get('ticket_type') == 'vip' else "Обычный 🎟"
            
            text = (
                f"✅ *Добавлен в список:*\n\n"
                f"*Фамилия:* {escape_markdown(last_name)}\n"
                f"*Имя:* {escape_markdown(first_name)}\n"
                f"*Тип билета:* {ticket_type_text}\n"
                f"*Контакт:* {escape_markdown(str(order['user_name']))}\n"
                f"*Telegram:* @{escape_markdown(str(order['username'] or 'без username'))}\n"
                f"*Уникальный код:* `{order['order_code']}`\n"
                f"*Время закрытия:* {closed_time}\n"
                f"*Промоутер:* @{escape_markdown(promoter_username)}"
            )
            
            await context.bot.send_message(
                chat_id=LISTS_CHANNEL_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
            
            await asyncio.sleep(0.5)
        
        logger.info(f"Информация о {len(guests)} гостях отправлена в канал списков для заказа #{order['order_id']}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки информации в канал списков: {e}")

async def send_new_order_notification(context: ContextTypes.DEFAULT_TYPE, order: Dict):
    """Отправить уведомление о новом заказе в чат промоутеров"""
    try:
        guests = db.get_order_guests(order['order_id'])
        
        created_at = order['created_at']
        if isinstance(created_at, str):
            created_date = created_at[:16].replace('T', ' ')
        else:
            created_date = created_at.strftime('%d.%m.%Y %H:%M')
        
        user_name = escape_markdown(str(order['user_name']))
        username = order['username'] if order['username'] else 'без username'
        escaped_username = escape_markdown(username)
        user_email = escape_markdown(str(order['user_email']))
        
        formatted_code = format_code_for_display(order['order_code'])
        
        ticket_type_text = "VIP 🎩" if order.get('ticket_type') == 'vip' else "Обычный 🎟"
        
        text = (
            "🆕 *Новая заявка!*\n\n"
            f"*Уникальный код:* `{order['order_code']}`\n"
            f"*Тип билета:* {ticket_type_text}\n"
            f"*ID заявки:* `{order['order_id']}`\n"
            f"*Контактное лицо:* {user_name}\n"
            f"*Telegram:* @{escaped_username}\n"
            f"*Email:* {user_email}\n"
            f"*User ID:* `{order['user_id']}`\n"
            f"*Количество человек:* {order['group_size']}\n"
            f"*Сумма заказа:* {order['total_amount']} ₽\n"
            f"*Дата создания:* {created_date}\n"
        )
        
        if guests:
            text += f"\n*Список гостей:*"
            for guest in guests:
                guest_name = escape_markdown(str(guest['full_name']))
                text += f"\n• {guest_name}"
        
        text += f"\n\n*💬 Способы связи:*"
        
        if username and username != 'без username' and username != 'None':
            clean_username = username.lstrip('@')
            text += f"\n• Telegram: @{clean_username}"
            text += f"\n• Ссылка: https://t.me/{clean_username}"
        else:
            text += f"\n• User ID: {order['user_id']}"
            text += f"\n• Ссылка: tg://user?id={order['user_id']}"
        
        text += f"\n• Email: {user_email}"
        
        # Создаем ссылку для обработки заявки в боте
        bot_username = context.bot.username
        bot_link = f"https://t.me/{bot_username}?start=order_{order['order_id']}"
        
        keyboard = [
            [InlineKeyboardButton("📋 Обработать заявку в боте", url=bot_link)],
            [InlineKeyboardButton("💬 Написать в диалог", url=f"tg://user?id={order['user_id']}")]
        ]
        
        try:
            await context.bot.send_message(
                chat_id=PROMOTERS_CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logger.info(f"Уведомление о новом заказе {order['order_id']} отправлено в чат промоутеров")
            
            db.mark_order_notified(order['order_id'])
            
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в чат промоутеров: {e}")
            
    except Exception as e:
        logger.error(f"Ошибка при формировании уведомления о новом заказе: {e}")

async def check_and_send_notifications(context: ContextTypes.DEFAULT_TYPE):
    """Проверить и отправить уведомления о новых заказах"""
    try:
        unnotified_orders = db.get_unnotified_orders()
        
        for order in unnotified_orders:
            await send_new_order_notification(context, order)
            await asyncio.sleep(1)
            
        if unnotified_orders:
            logger.info(f"Отправлено уведомлений о {len(unnotified_orders)} новых заказах")
            
    except Exception as e:
        logger.error(f"Ошибка при проверке и отправке уведомлений: {e}")

def is_own_order(order: Dict, user_id: int) -> bool:
    """Проверяет, является ли заказ собственным для пользователя"""
    return order["user_id"] == user_id

# ========== КЛАВИАТУРЫ ==========
def get_role_selection_keyboard(user_id: int):
    """Клавиатура выбора роли"""
    keyboard = []
    
    is_admin = user_id in ADMIN_IDS
    is_promoter = user_id in PROMOTER_IDS
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚡️ Войти в админ-панель", callback_data="select_admin")])
    
    if is_promoter:
        keyboard.append([InlineKeyboardButton("👨‍💼 Войти как промоутер", callback_data="select_promoter")])
    
    keyboard.append([InlineKeyboardButton("👤 Пользователь", callback_data="select_user")])
    
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard(user_role: str = "user"):
    """Клавиатура главного меню"""
    if user_role == "admin":
        keyboard = [
            [InlineKeyboardButton("💰 Узнать цену", callback_data="price_info"),
             InlineKeyboardButton("🎟 Купить билет", callback_data="buy_start")],
            [InlineKeyboardButton("🎪 Событие", callback_data="event_info"),
             InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton("⚡️ Админ-панель", callback_data="admin_menu"),
             InlineKeyboardButton("👨‍💼 Панель промоутера", callback_data="promoter_menu")]
        ]
    elif user_role == "promoter":
        keyboard = [
            [InlineKeyboardButton("💰 Узнать цену", callback_data="price_info"),
             InlineKeyboardButton("🎟 Купить билет", callback_data="buy_start")],
            [InlineKeyboardButton("🎪 Событие", callback_data="event_info"),
             InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")],
            [InlineKeyboardButton("👨‍💼 Панель промоутера", callback_data="promoter_menu"),
             InlineKeyboardButton("⚡️ Сменить роль", callback_data="change_role")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("💰 Узнать цену", callback_data="price_info"),
             InlineKeyboardButton("🎟 Купить билет", callback_data="buy_start")],
            [InlineKeyboardButton("🎪 Событие", callback_data="event_info"),
             InlineKeyboardButton("📋 Мои заказы", callback_data="my_orders")]
        ]
    
    return InlineKeyboardMarkup(keyboard)

def get_ticket_type_keyboard():
    """Клавиатура выбора типа билета"""
    keyboard = [
        [InlineKeyboardButton("🎟 Обычный билет", callback_data="ticket_standard")],
        [InlineKeyboardButton("🎩 VIP билет", callback_data="ticket_vip")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_group_size_keyboard():
    """Клавиатура выбора количества людей"""
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data="size_1"),
            InlineKeyboardButton("2", callback_data="size_2"),
            InlineKeyboardButton("3", callback_data="size_3"),
            InlineKeyboardButton("4", callback_data="size_4")
        ],
        [
            InlineKeyboardButton("5", callback_data="size_5"),
            InlineKeyboardButton("6", callback_data="size_6"),
            InlineKeyboardButton("7", callback_data="size_7"),
            InlineKeyboardButton("8", callback_data="size_8")
        ],
        [
            InlineKeyboardButton("9", callback_data="size_9"),
            InlineKeyboardButton("10", callback_data="size_10"),
            InlineKeyboardButton("10+", callback_data="size_10_plus")
        ],
        [
            InlineKeyboardButton("✏️ Другое число", callback_data="size_custom"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    """Клавиатура администратора"""
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton("🎪 Редактировать 'Событие'", callback_data="edit_event_info_text")],
        [InlineKeyboardButton("🔄 Сбросить статистику", callback_data="admin_reset_stats")],
        [InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_promoter_keyboard():
    """Клавиатура промоутера"""
    keyboard = [
        [InlineKeyboardButton("📋 Активные заявки", callback_data="promoter_active")],
        [InlineKeyboardButton("⏳ Отложенные", callback_data="promoter_deferred")],
        [InlineKeyboardButton("🔙 В главное меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_settings_keyboard():
    """Клавиатура настроек администратора"""
    keyboard = [
        [InlineKeyboardButton("💰 Изменить цены", callback_data="edit_prices")],
        [InlineKeyboardButton("📞 Изменить контакты", callback_data="edit_contacts")],
        [InlineKeyboardButton("🔄 Сбросить настройки", callback_data="reset_settings")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_reset_stats_keyboard():
    """Клавиатура сброса статистики"""
    keyboard = [
        [InlineKeyboardButton("✅ Да, сбросить всё", callback_data="confirm_reset_all")],
        [InlineKeyboardButton("👥 Сбросить только список гостей", callback_data="confirm_reset_guests")],
        [InlineKeyboardButton("❌ Нет, отмена", callback_data="admin_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_price_edit_keyboard():
    """Клавиатура редактирования цен"""
    settings = event_settings.get_all_settings()
    keyboard = [
        [InlineKeyboardButton(f"Стандартная: {settings['price_standard']}₽", callback_data="edit_price_standard")],
        [InlineKeyboardButton(f"Групповая: {settings['price_group']}₽", callback_data="edit_price_group")],
        [InlineKeyboardButton(f"VIP: {settings['price_vip']}₽", callback_data="edit_price_vip")],
        [InlineKeyboardButton(f"Порог: {settings['group_threshold']}+ человек", callback_data="edit_group_threshold")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_contacts_edit_keyboard():
    """Клавиатура редактирования контактов"""
    settings = event_settings.get_all_settings()
    keyboard = [
        [InlineKeyboardButton(f"Telegram: {settings['contact_telegram']}", callback_data="edit_contact_telegram")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_confirmation_keyboard():
    """Клавиатура подтверждения покупки"""
    keyboard = [
        [InlineKeyboardButton("✅ Купить билет", callback_data="confirm_buy")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_buy")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_order_actions_keyboard(order_id: str, user_id: int, username: str = None, is_own_order: bool = False):
    """Клавиатура действий с заказом для промоутера"""
    keyboard = []
    
    if not is_own_order:
        if username and username != 'без username' and username != 'None':
            clean_username = username.lstrip('@')
            chat_link = f"https://t.me/{clean_username}"
            keyboard.append([InlineKeyboardButton("💬 Перейти в диалог", url=chat_link)])
        else:
            keyboard.append([InlineKeyboardButton("💬 Перейти в диалог", url=f"tg://user?id={user_id}")])
        
        keyboard.append([InlineKeyboardButton("✅ Закрыть заявку", callback_data=f"close_order_{order_id}")])
        keyboard.append([InlineKeyboardButton("⏳ Отложить", callback_data=f"defer_order_{order_id}")])
        keyboard.append([InlineKeyboardButton("❌ Возврат", callback_data=f"refund_order_{order_id}")])
    else:
        keyboard.append([InlineKeyboardButton("❌ Это ваш заказ, вы не можете его обработать", callback_data="promoter_active")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="promoter_active")])
    
    return InlineKeyboardMarkup(keyboard)

def get_back_to_promoter_keyboard():
    """Клавиатура возврата в меню промоутера"""
    keyboard = [
        [InlineKeyboardButton("🔙 В меню промоутера", callback_data="promoter_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== ФОРМАТИРОВАНИЕ ==========
def format_price_info() -> str:
    """Форматировать информацию о ценах"""
    settings = event_settings.get_all_settings()
    
    text = (
        f"💰 *Цены на билеты {settings['event_name']}:*\n\n"
        f"• 🎟 *Обычный билет:*\n"
        f"  - 1 человек: *{settings['price_standard']} ₽*\n"
        f"  - Группа от {settings['group_threshold']}+ человек: *{settings['price_group']} ₽/чел.*\n\n"
        f"• 🎩 *VIP билет:*\n"
        f"  - Цена за человека: *{settings['price_vip']} ₽*\n\n"
        f"🎉 *Акция:* Экономия *{settings['price_standard'] - settings['price_group']} ₽* с каждого в группе!\n\n"
        f"Хотите купить билеты?"
    )
    
    return text

def format_price_calculation(group_size: int, ticket_type: str = "standard") -> str:
    """Форматировать расчет цены"""
    settings = event_settings.get_all_settings()
    
    if ticket_type == "vip":
        price_per_person = settings['price_vip']
        total = price_per_person * group_size
        
        text = f"🎩 *Расчет для {group_size} VIP билетов:*\n\n"
        text += f"• Цена за VIP билет: *{price_per_person} ₽*\n"
        text += f"• Общая сумма: *{total} ₽*\n"
        text += f"\n_Цена VIP билета всегда фиксированная: {settings['price_vip']} ₽_"
        
    else:
        if group_size >= settings['group_threshold']:
            price_per_person = settings['price_group']
        else:
            price_per_person = settings['price_standard']
        
        total = price_per_person * group_size
        
        text = f"🎟 *Расчет для {group_size} обычных билетов:*\n\n"
        text += f"• Цена за билет: *{price_per_person} ₽*\n"
        text += f"• Общая сумма: *{total} ₽*\n"
        
        if group_size >= settings['group_threshold']:
            economy = (settings['price_standard'] - settings['price_group']) * group_size
            text += f"\n✅ *Вы получаете групповую скидку!*\n"
            text += f"Экономия: *{economy} ₽*\n"
        
        text += f"\n_Цена для 1 человека: {settings['price_standard']} ₽_\n"
        text += f"_Группа от {settings['group_threshold']}+ человек: {settings['price_group']} ₽/чел._"
    
    return text

def format_order_summary(name: str, email: str, group_size: int, guests: List[str], ticket_type: str = "standard") -> str:
    """Форматировать сводку заказа"""
    settings = event_settings.get_all_settings()
    total = event_settings.calculate_price(group_size, ticket_type)
    
    if ticket_type == "vip":
        price_per_person = settings['price_vip']
        ticket_type_text = "VIP 🎩"
    else:
        price_per_person = settings['price_group'] if group_size >= settings['group_threshold'] else settings['price_standard']
        ticket_type_text = "Обычный 🎟"
    
    escaped_name = escape_markdown(str(name))
    escaped_email = escape_markdown(str(email))
    escaped_guests = [escape_markdown(str(guest)) for guest in guests]
    
    summary = "📋 *Сводка вашего заказа:*\n\n"
    summary += f"• Тип билета: *{ticket_type_text}*\n"
    summary += f"• Количество человек: *{group_size}*\n"
    summary += f"• Цена за билет: *{price_per_person} ₽*\n"
    summary += f"• Общая сумма: *{total} ₽*\n\n"
    
    summary += f"• Контактное лицо: *{escaped_name}*\n"
    summary += f"• Email: *{escaped_email}*\n"
    
    if guests:
        summary += "\n• *Список гостей:*\n"
        for i, guest in enumerate(escaped_guests, 1):
            summary += f"  {i}. {guest}\n"
    
    summary += f"\n*Подтвердить покупку?*"
    
    return summary

def format_event_info() -> str:
    """Форматировать информацию о мероприятии"""
    event_info_text = event_settings.get_all_settings().get('event_info_text', '')
    
    if event_info_text:
        try:
            return event_info_text
        except Exception as e:
            logger.error(f"Ошибка форматирования event_info_text: {e}")
            return event_info_text
    else:
        settings = event_settings.get_all_settings()
        
        event_name = str(settings.get('event_name', 'SMILE PARTY 🎉'))
        event_address = str(settings.get('event_address', 'Адрес не указан'))
        event_date = str(settings.get('event_date', 'Дата не указана'))
        event_time = str(settings.get('event_time', 'Время не указано'))
        event_age_limit = str(settings.get('event_age_limit', '18+'))
        contact_telegram = str(settings.get('contact_telegram', '@smile_party'))
        
        description = settings.get('description', '')
        if description is None:
            description = ""
        description = str(description)
        
        escaped_name = escape_markdown(event_name)
        escaped_address = escape_markdown(event_address)
        escaped_description = escape_markdown(description)
        
        text = (
            f"🏢 *Информация о мероприятии*\n\n"
            f"*🎉 Название:* {escaped_name}\n"
            f"*📍 Адрес:* {escaped_address}\n"
            f"*📅 Дата:* {event_date}\n"
            f"*⏰ Время:* {event_time}\n"
            f"*🎭 Возраст:* {event_age_limit}\n"
            f"*📱 Telegram:* {contact_telegram}\n"
        )
        
        if escaped_description.strip():
            text += f"\n*📝 Описание:*\n{escaped_description}"
        
        return text

def format_order_details_for_promoter(order: Dict, is_own_order: bool = False) -> str:
    """Форматировать детали заказа для промоутера"""
    try:
        guests = db.get_order_guests(order['order_id'])
        
        user_name = escape_markdown(str(order['user_name']))
        username = order['username'] if order['username'] else 'без username'
        escaped_username = escape_markdown(username)
        user_email = escape_markdown(str(order['user_email']))
        
        created_at = order['created_at']
        if isinstance(created_at, str):
            created_date = created_at[:16].replace('T', ' ')
        else:
            created_date = created_at.strftime('%d.%m.%Y %H:%M')
        
        formatted_code = format_code_for_display(order['order_code'])
        
        ticket_type_text = "VIP 🎩" if order.get('ticket_type') == 'vip' else "Обычный 🎟"
        
        text = (
            f"📋 *Детали заказа #{order['order_id']}*\n\n"
            f"*🔑 Уникальный код:* `{order['order_code']}`\n"
            f"*🎫 Тип билета:* {ticket_type_text}\n\n"
            f"👤 *Контактное лицо:* {user_name}\n"
            f"📱 *Telegram:* @{escaped_username}\n"
            f"📧 *Email:* {user_email}\n"
            f"🆔 *User ID:* `{order['user_id']}`\n"
            f"👥 *Количество человек:* {order['group_size']}\n"
            f"💰 *Сумма заказа:* {order['total_amount']} ₽\n"
            f"📅 *Дата создания:* {created_date}\n"
            f"📊 *Статус:* {order['status']}"
        )
        
        if order.get('assigned_promoter'):
            assigned_promoter = escape_markdown(str(order['assigned_promoter']))
            text += f"\n👨‍💼 *Назначен:* @{assigned_promoter}"
        
        if guests:
            text += f"\n\n📝 *Список гостей:*"
            for guest in guests:
                guest_name = escape_markdown(str(guest['full_name']))
                text += f"\n• {guest_name}"
        
        text += f"\n\n*💬 Способы связи:*"
        
        if username and username != 'без username' and username != 'None':
            clean_username = username.lstrip('@')
            text += f"\n• Telegram: @{clean_username}"
            text += f"\n• Ссылка: https://t.me/{clean_username}"
        else:
            text += f"\n• User ID: {order['user_id']}"
            text += f"\n• Ссылка: tg://user?id={order['user_id']}"
        
        text += f"\n• Email: {user_email}"
        
        if is_own_order:
            text += f"\n\n⚠️ *ВНИМАНИЕ:* Это ваш собственный заказ! Вы не можете его обработать."
        
        return text
    except Exception as e:
        logger.error(f"Ошибка при форматировании деталей заказа: {e}")
        return f"📋 *Детали заказа #{order['order_id']}*\n\n👤 *Контакт:* {escape_markdown(str(order['user_name']))}\n💰 *Сумма:* {order['total_amount']} ₽"

def format_statistics() -> str:
    """Форматировать статистику"""
    stats = db.get_statistics()
    
    text = (
        "📊 *Статистика*\n\n"
        f"📋 *Всего заказов:* {stats.get('total_orders', 0)}\n"
        f"🟢 *Активные:* {stats.get('active_orders', 0)}\n"
        f"⏳ *Отложенные:* {stats.get('deferred_orders', 0)}\n"
        f"✅ *Закрытые:* {stats.get('closed_orders', 0)}\n"
        f"❌ *Возвраты:* {stats.get('refunded_orders', 0)}\n"
        f"💰 *Выручка:* {stats.get('revenue', 0)} ₽\n"
        f"👥 *Всего гостей в списках:* {stats.get('total_guests', 0)}\n\n"
        f"🎟 *Обычные билеты:*\n"
        f"• Продано: {stats.get('standard_tickets', 0)}\n"
        f"• Выручка: {stats.get('standard_revenue', 0)} ₽\n\n"
        f"🎩 *VIP билеты:*\n"
        f"• Продано: {stats.get('vip_tickets', 0)}\n"
        f"• Выручка: {stats.get('vip_revenue', 0)} ₽"
    )
    
    return text

# ========== УВЕДОМЛЕНИЯ ПРИ ЗАПУСКЕ ==========
async def send_restart_notifications_async(bot_token: str):
    """Асинхронная функция для отправки уведомлений о перезапуске"""
    try:
        from telegram import Bot
        
        bot = Bot(token=bot_token)
        users = db.get_users_to_notify()
        settings_data = event_settings.get_all_settings()
        
        notification_count = 0
        for user in users:
            try:
                await bot.send_message(
                    chat_id=user['user_id'],
                    text=f"🔄 *{escape_markdown(str(settings_data['event_name']))} бот перезапущен!*\n\n"
                         f"Бот снова в сети и готов к работе.\n"
                         f"Используйте /start для начала работы.",
                    parse_mode=ParseMode.MARKDOWN
                )
                db.mark_user_notified(user['user_id'])
                notification_count += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление пользователю {user['user_id']}: {e}")
        
        logger.info(f"✅ Отправлено {notification_count} уведомлений при перезапуске бота")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений при перезапуске: {e}")

def send_restart_notifications():
    """Синхронная функция для отправки уведомлений о перезапуске"""
    import asyncio
    asyncio.run(send_restart_notifications_async(BOT_TOKEN))

async def send_order_notification_to_user(context: ContextTypes.DEFAULT_TYPE, order: Dict, action: str, promoter_username: str):
    """Отправить уведомление пользователю о действии с его заказом"""
    try:
        if order['user_id']:
            escaped_promoter = escape_markdown(promoter_username)
            escaped_user_name = escape_markdown(str(order['user_name']))
            formatted_code = format_code_for_display(order['order_code'])
            
            ticket_type_text = "VIP 🎩" if order.get('ticket_type') == 'vip' else "Обычный 🎟"
            
            if action == "closed":
                message = (
                    f"✅ *Ваш заказ #{order['order_id']} успешно обработан!*\n\n"
                    f"*Тип билета:* {ticket_type_text}\n"
                    f"*Ваш уникальный код:* `{order['order_code']}`\n\n"
                    f"Промоутер @{escaped_promoter} подтвердил вашу покупку.\n\n"
                    f"*Детали заказа:*\n"
                    f"• Контактное лицо: {escaped_user_name}\n"
                    f"• Количество гостей: {order['group_size']}\n"
                    f"• Сумма: {order['total_amount']} ₽\n\n"
                    f"*💾 Сохраните ваш код! Он потребуется при входе на мероприятие.*\n\n"
                    f"Спасибо за покупку! Ждем вас на мероприятии! 🎉"
                )
            elif action == "refunded":
                message = (
                    f"❌ *По вашему заказу #{order['order_id']} оформлен возврат*\n\n"
                    f"*Тип билета:* {ticket_type_text}\n"
                    f"*Код заказа:* `{order['order_code']}`\n\n"
                    f"Промоутер @{escaped_promoter} оформил возврат по вашему заказу.\n\n"
                    f"Если у вас есть вопросы, свяжитесь с поддержкой: {event_settings.get_all_settings()['contact_telegram']}"
                )
            else:
                return
            
            await context.bot.send_message(
                chat_id=order['user_id'],
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Уведомление отправлено пользователю {order['user_id']}")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю: {e}")

# ========== ОСНОВНЫЕ КОМАНДЫ ==========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /start с поддержкой параметров"""
    try:
        user = update.effective_user
        message_text = update.message.text
        
        db.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        
        context.user_data.clear()
        
        # Проверяем, есть ли параметры в команде /start
        if ' ' in message_text:
            params = message_text.split(' ', 1)[1]
            
            # Если параметр начинается с order_, это переход на заказ
            if params.startswith('order_'):
                order_id = params.replace('order_', '')
                order = db.get_order(order_id)
                
                if order and user.id in PROMOTER_IDS:
                    # Проверяем, не свой ли это заказ
                    own_order = is_own_order(order, user.id)
                    
                    if own_order:
                        await update.message.reply_text(
                            "❌ *Это ваш собственный заказ!*\n\n"
                            "Вы не можете обрабатывать свой собственный заказ.\n"
                            "Пожалуйста, выберите другой заказ для обработки.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    else:
                        # Показываем детали заказа
                        username = user.username or f"user_{user.id}"
                        context.user_data['user_role'] = 'promoter'
                        
                        text = format_order_details_for_promoter(order, own_order)
                        username_for_link = order['username'] if order['username'] and order['username'] != 'без username' and order['username'] != 'None' else None
                        
                        await update.message.reply_text(
                            text,
                            reply_markup=get_order_actions_keyboard(order_id, order['user_id'], username_for_link, own_order),
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return PROMOTER_VIEW_ORDER
        
        role = get_user_role(user.id)
        
        if role == "admin" or role == "promoter":
            settings_data = event_settings.get_all_settings()
            await update.message.reply_text(
                f"🎉 *Добро пожаловать в {escape_markdown(str(settings_data['event_name']))}!*\n\n"
                f"Пожалуйста, выберите, как вы хотите войти:",
                reply_markup=get_role_selection_keyboard(user.id),
                parse_mode=ParseMode.MARKDOWN
            )
            return ROLE_SELECTION
        else:
            context.user_data['user_role'] = 'user'
            settings_data = event_settings.get_all_settings()
            await update.message.reply_text(
                f"🎉 *Добро пожаловать в {escape_markdown(str(settings_data['event_name']))}!*\n\n"
                f"Выберите действие:",
                reply_markup=get_main_menu_keyboard('user'),
                parse_mode=ParseMode.MARKDOWN
            )
            return MAIN_MENU
    except Exception as e:
        logger.error(f"Ошибка в start_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка при запуске бота.")
        return MAIN_MENU

# ========== ОБРАБОТЧИКИ КНОПОК ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    username = query.from_user.username or f"user_{user_id}"
    data = query.data
    
    try:
        if data.startswith("select_"):
            role = data.replace("select_", "")
            
            if role == "admin" and user_id not in ADMIN_IDS:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_role_selection_keyboard(user_id),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ROLE_SELECTION
            
            if role == "promoter" and user_id not in PROMOTER_IDS:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_role_selection_keyboard(user_id),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ROLE_SELECTION
            
            context.user_data['user_role'] = role
            
            if role == "admin":
                await query.edit_message_text(
                    "⚡️ *Вы вошли как администратор*\n\n"
                    "Выберите действие:",
                    reply_markup=get_main_menu_keyboard(role),
                    parse_mode=ParseMode.MARKDOWN
                )
            elif role == "promoter":
                await query.edit_message_text(
                    "👨‍💼 *Вы вошли как промоутер*\n\n"
                    "Выберите действие:",
                    reply_markup=get_main_menu_keyboard(role),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text(
                    "👤 *Вы вошли как пользователь*\n\n"
                    "Выберите действие:",
                    reply_markup=get_main_menu_keyboard(role),
                    parse_mode=ParseMode.MARKDOWN
                )
            
            return MAIN_MENU
        
        elif data == "price_info":
            await query.edit_message_text(
                format_price_info(),
                reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                parse_mode=ParseMode.MARKDOWN
            )
            return MAIN_MENU
        
        elif data == "event_info":
            try:
                text = format_event_info()
                
                try:
                    await query.edit_message_text(
                        text,
                        reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except BadRequest as e:
                    logger.error(f"Ошибка при отправке Markdown: {e}")
                    plain_text = text.replace('*', '').replace('_', '').replace('`', '')
                    await query.edit_message_text(
                        plain_text,
                        reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user'))
                    )
                
            except Exception as e:
                logger.error(f"Ошибка при отображении информации о мероприятии: {e}")
                settings_data = event_settings.get_all_settings()
                simple_text = (
                    f"🏢 Информация о мероприятии\n\n"
                    f"🎉 Название: {settings_data.get('event_name', 'SMILE PARTY')}\n"
                    f"📍 Адрес: {settings_data.get('event_address', 'Адрес не указан')}\n"
                    f"📅 Дата: {settings_data.get('event_date', 'Дата не указана')}\n"
                    f"⏰ Время: {settings_data.get('event_time', 'Время не указано')}\n"
                    f"🎭 Возраст: {settings_data.get('event_age_limit', '18+')}\n"
                    f"📱 Telegram: {settings_data.get('contact_telegram', '@smile_party')}"
                )
                
                await query.edit_message_text(
                    simple_text,
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user'))
                )
            
            return MAIN_MENU
        
        elif data == "my_orders":
            orders = db.get_user_orders(user_id)
            
            if not orders:
                keyboard = [
                    [InlineKeyboardButton("🎟 Купить билет", callback_data="buy_start")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
                ]
                
                await query.edit_message_text(
                    "📭 *У вас пока нет заказов*\n\n"
                    "Хотите купить билет?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                orders_text = "📋 *Ваши заказы:*\n\n"
                for order in orders[:10]:
                    status_emoji = {
                        "active": "🟢",
                        "deferred": "⏳",
                        "closed": "✅",
                        "refunded": "❌"
                    }.get(order["status"], "❓")
                    
                    ticket_type_emoji = "🎩" if order.get('ticket_type') == 'vip' else "🎟"
                    
                    created_at = order['created_at']
                    if isinstance(created_at, str):
                        created_date = created_at[:10]
                    else:
                        created_date = created_at.strftime('%d.%m.%Y')
                    
                    formatted_code = format_code_for_display(order.get('order_code', 'НЕТ КОДА'))
                    
                    orders_text += (
                        f"{status_emoji} *Заказ #{order['order_id']}* {ticket_type_emoji}\n"
                        f"🔑 Код: `{order.get('order_code', 'НЕТ КОДА')}`\n"
                        f"👥 {order['group_size']} чел. | "
                        f"💰 {order['total_amount']} ₽ | "
                        f"📅 {created_date}\n"
                        f"Статус: {order['status']}\n\n"
                    )
                
                if len(orders_text) > 4096:
                    orders_text = orders_text[:4000] + "...\n\n⚠️ Слишком много заказов, показаны только последние."
                
                keyboard = [
                    [InlineKeyboardButton("🎟 Новый заказ", callback_data="buy_start")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
                ]
                
                await query.edit_message_text(
                    orders_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            
            return MAIN_MENU
        
        elif data == "back_to_menu":
            role = context.user_data.get('user_role', 'user')
            await query.edit_message_text(
                f"🏠 *Главное меню*\n\n"
                f"Выберите действие:",
                reply_markup=get_main_menu_keyboard(role),
                parse_mode=ParseMode.MARKDOWN
            )
            return MAIN_MENU
        
        elif data == "buy_start":
            await query.edit_message_text(
                "🎫 *Покупка билета*\n\n"
                "Сначала выберите тип билета:",
                reply_markup=get_ticket_type_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            return BUY_TICKET_TYPE
        
        elif data in ["ticket_standard", "ticket_vip"]:
            if data == "ticket_standard":
                context.user_data['ticket_type'] = 'standard'
                ticket_type_text = "обычный"
            else:
                context.user_data['ticket_type'] = 'vip'
                ticket_type_text = "VIP"
            
            await query.edit_message_text(
                f"🎟 *Покупка {ticket_type_text} билета*\n\n"
                "Теперь выберите количество человек:",
                reply_markup=get_group_size_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            return BUY_TICKET_TYPE
        
        elif data.startswith("size_"):
            size_data = data.replace("size_", "")
            
            if size_data == "custom":
                await query.edit_message_text(
                    "✏️ *Введите количество человек цифрами*\n\n"
                    "Можно указать любое число от 1 до 100\n"
                    "Например: 15, 25, 50",
                    parse_mode=ParseMode.MARKDOWN
                )
                return BUY_TICKET_TYPE
            
            elif size_data == "10_plus":
                context.user_data['group_size'] = 15
                await query.edit_message_text(
                    "✏️ *Введите количество человек цифрами*\n\n"
                    "Можно указать любое число от 10 до 100\n"
                    "Например: 12, 20, 45",
                    parse_mode=ParseMode.MARKDOWN
                )
                return BUY_TICKET_TYPE
            else:
                try:
                    group_size = int(size_data)
                except:
                    group_size = 1
            
            context.user_data['group_size'] = group_size
            context.user_data['guests'] = []
            
            ticket_type = context.user_data.get('ticket_type', 'standard')
            
            await query.edit_message_text(
                format_price_calculation(group_size, ticket_type) + "\n\n"
                "👉 *Продолжить покупку?*",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Да, продолжить", callback_data="buy_continue")],
                    [InlineKeyboardButton("❌ Нет, отмена", callback_data="back_to_menu")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
            return BUY_TICKET_TYPE
        
        elif data == "buy_continue":
            context.user_data['in_buy_process'] = True
            
            await query.edit_message_text(
                "👤 *Введите ваше имя и фамилию (контактное лицо)*\n\n"
                "Например: Александр Иванов",
                parse_mode=ParseMode.MARKDOWN
            )
            return BUY_NAME
        
        elif data == "confirm_buy":
            required_fields = ['name', 'email', 'group_size', 'guests', 'ticket_type']
            if not all(field in context.user_data for field in required_fields):
                await query.edit_message_text(
                    "❌ *Ошибка: недостаточно данных*\n\n"
                    "Пожалуйста, начните покупку заново.",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
            
            current_hour = datetime.now().hour
            is_night_time = current_hour >= 23 or current_hour < 8
            
            total_amount = event_settings.calculate_price(
                context.user_data['group_size'], 
                context.user_data['ticket_type']
            )
            
            order_data = db.create_order(
                user_id=user_id,
                username=username,
                user_name=context.user_data['name'],
                user_email=context.user_data['email'],
                group_size=context.user_data['group_size'],
                ticket_type=context.user_data['ticket_type'],
                total_amount=total_amount
            )
            
            if not order_data:
                await query.edit_message_text(
                    "❌ *Ошибка при создании заказа*\n\n"
                    "Пожалуйста, попробуйте еще раз.",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
            
            order_id = order_data['order_id']
            order_code = order_data['order_code']
            formatted_code = format_code_for_display(order_code)
            
            if not db.add_guests_to_order(order_id, order_code, context.user_data['guests']):
                await query.edit_message_text(
                    "❌ *Ошибка при добавлении гостей*\n\n"
                    "Заказ создан, но возникла проблема с сохранением списка гостей.",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
            
            settings_data = event_settings.get_all_settings()
            
            ticket_type_text = "VIP 🎩" if context.user_data['ticket_type'] == 'vip' else "Обычный 🎟"
            
            confirmation_text = (
                f"🎉 ЗАКАЗ #{order_id} УСПЕШНО СОЗДАН!\n\n"
                f"*🎫 Тип билета:* {ticket_type_text}\n"
                f"*🔑 Ваш уникальный код:* `{order_code}`\n\n"
                f"👤 Контактное лицо: {escape_markdown(str(context.user_data['name']))}\n"
                f"📧 Email: {escape_markdown(str(context.user_data['email']))}\n"
                f"👥 Количество: {context.user_data['group_size']} чел.\n"
                f"💰 Сумма: {total_amount} ₽\n\n"
                f"*💾 Сохраните ваш код! Он потребуется при входе на мероприятие.*\n\n"
            )
            
            if is_night_time:
                confirmation_text += (
                    "⏰ ВНИМАНИЕ! Вы оформили заказ в нерабочее время (23:00 - 08:00).\n"
                    "Промоутеры свяжутся с вами утром для подтверждения.\n\n"
                )
            else:
                confirmation_text += (
                    "ЧТО ДАЛЬШЕ?\n"
                    "1. Все гости добавлены в списки на вход\n"
                    "2. В течение 30 минут с вами свяжется промоутер\n"
                    "3. Он подтвердит покупку\n\n"
                )
            
            confirmation_text += f"СПАСИБО ЗА ПОКУПКУ В {settings_data['event_name']}! 🎊"
            
            await query.message.reply_text(confirmation_text, parse_mode=ParseMode.MARKDOWN)
            
            order = db.get_order(order_id)
            if order:
                await send_new_order_notification(context, order)
            
            context.user_data.pop('in_buy_process', None)
            context.user_data.pop('name', None)
            context.user_data.pop('email', None)
            context.user_data.pop('group_size', None)
            context.user_data.pop('guests', None)
            context.user_data.pop('guest_counter', None)
            context.user_data.pop('ticket_type', None)
            
            await query.message.reply_text(
                "Выберите дальнейшее действие:",
                reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user'))
            )
            
            return MAIN_MENU
        
        elif data == "cancel_buy":
            context.user_data.pop('in_buy_process', None)
            context.user_data.pop('name', None)
            context.user_data.pop('email', None)
            context.user_data.pop('group_size', None)
            context.user_data.pop('guests', None)
            context.user_data.pop('guest_counter', None)
            context.user_data.pop('ticket_type', None)
            
            await query.edit_message_text(
                "❌ *Покупка отменена*\n\n"
                "Если передумаете — всегда можете создать новый заказ!",
                reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                parse_mode=ParseMode.MARKDOWN
            )
            
            return MAIN_MENU
        
        elif data == "admin_menu":
            if user_id in ADMIN_IDS:
                await query.edit_message_text(
                    "⚡️ *Панель администратора*\n\n"
                    "Выберите действие:",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ADMIN_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "admin_back":
            await query.edit_message_text(
                "⚡️ *Панель администратора*",
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            return ADMIN_MENU
        
        elif data == "admin_stats":
            if user_id in ADMIN_IDS:
                stats_text = format_statistics()
                await query.edit_message_text(
                    stats_text,
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ADMIN_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "admin_reset_stats":
            if user_id in ADMIN_IDS:
                await query.edit_message_text(
                    "🔄 *Сброс статистики*\n\n"
                    "⚠️ *ВНИМАНИЕ!* Это действие удалит:\n"
                    "• Все заказы\n"
                    "• Всех гостей\n"
                    "• Всю историю\n\n"
                    "Выберите действие:",
                    reply_markup=get_reset_stats_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ADMIN_RESET_STATS
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "confirm_reset_all":
            if user_id in ADMIN_IDS:
                with closing(db.get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM guests")
                    cursor.execute("DELETE FROM orders")
                    conn.commit()
                
                await query.edit_message_text(
                    "✅ *Вся статистика успешно сброшена!*\n\n"
                    "Все заказы и гости удалены.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text(
                    "❌ *Ошибка при сбросе статистики*",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            return ADMIN_MENU
        
        elif data == "confirm_reset_guests":
            if user_id in ADMIN_IDS and db.reset_guests_count():
                await query.edit_message_text(
                    "✅ *Список гостей успешно сброшен!*\n\n"
                    "Все гости удалены из базы данных.",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text(
                    "❌ *Ошибка при сбросе списка гостей*",
                    reply_markup=get_admin_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            return ADMIN_MENU
        
        elif data == "admin_settings":
            if user_id in ADMIN_IDS:
                await query.edit_message_text(
                    "⚙️ *Настройки мероприятия*\n\n"
                    "Выберите, что хотите изменить:",
                    reply_markup=get_admin_settings_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ADMIN_EDIT
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "edit_prices":
            if user_id in ADMIN_IDS:
                await query.edit_message_text(
                    "💰 *Редактирование цен*\n\n"
                    "Выберите настройку для изменения:",
                    reply_markup=get_price_edit_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ADMIN_EDIT
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "edit_contacts":
            if user_id in ADMIN_IDS:
                await query.edit_message_text(
                    "📞 *Редактирование контактов*\n\n"
                    "Выберите настройку для изменения:",
                    reply_markup=get_contacts_edit_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ADMIN_EDIT
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "edit_event_info_text":
            if user_id in ADMIN_IDS:
                context.user_data['editing_key'] = "event_info_text"
                context.user_data['editing_name'] = "текст кнопки 'Событие'"
                
                current_text = event_settings.get_all_settings().get('event_info_text', '')
                if current_text:
                    display_text = current_text
                else:
                    display_text = ""
                
                if len(display_text) > 2000:
                    display_text = display_text[:2000] + "...\n\n[текст слишком длинный, показаны первые 2000 символов]"
                
                await query.edit_message_text(
                    f"✏️ Редактирование текста кнопки 'Событие'\n\n"
                    f"Текущий текст:\n\n{display_text}\n\n"
                    f"Введите новый текст (можно использовать Markdown форматирование, например *жирный* или _курсив_):",
                    parse_mode=None
                )
                return ADMIN_EDIT_TEXT
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "reset_settings":
            if user_id in ADMIN_IDS:
                keyboard = [
                    [InlineKeyboardButton("✅ Да, сбросить", callback_data="confirm_reset_settings")],
                    [InlineKeyboardButton("❌ Нет, отмена", callback_data="admin_settings")]
                ]
                
                await query.edit_message_text(
                    "🔄 *Сброс настроек*\n\n"
                    "Вы уверены, что хотите сбросить все настройки к значениям по умолчанию?\n\n"
                    "⚠️ *Это действие нельзя отменить!*",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
                return ADMIN_EDIT
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "confirm_reset_settings":
            if user_id in ADMIN_IDS and event_settings.reset_to_defaults():
                await query.edit_message_text(
                    "✅ *Настройки сброшены к значениям по умолчанию!*",
                    reply_markup=get_admin_settings_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text(
                    "❌ *Ошибка при сбросе настроек*",
                    reply_markup=get_admin_settings_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            return ADMIN_EDIT
        
        elif data.startswith("edit_"):
            if user_id in ADMIN_IDS:
                setting_map = {
                    "edit_price_standard": ("стандартную цену (1 человек)", "price_standard"),
                    "edit_price_group": ("групповую цену", "price_group"),
                    "edit_price_vip": ("VIP цену", "price_vip"),
                    "edit_group_threshold": ("порог для групповой цены", "group_threshold"),
                    "edit_contact_telegram": ("контакт в Telegram", "contact_telegram")
                }
                
                if data in setting_map:
                    setting_name, setting_key = setting_map[data]
                    current_value = event_settings.get_all_settings().get(setting_key, "")
                    
                    context.user_data['editing_key'] = setting_key
                    context.user_data['editing_name'] = setting_name
                    
                    await query.edit_message_text(
                        f"✏️ *Редактирование {setting_name}*\n\n"
                        f"Текущее значение: *{current_value}*\n\n"
                        f"Введите новое значение:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return ADMIN_EDIT_TEXT
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав администратора*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "promoter_menu":
            if user_id in PROMOTER_IDS:
                await query.edit_message_text(
                    "👨‍💼 *Панель промоутера*\n\n"
                    "Выберите действие:",
                    reply_markup=get_promoter_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return PROMOTER_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "promoter_active":
            if user_id in PROMOTER_IDS:
                active_orders = db.get_orders_by_status("active")
                
                filtered_orders = []
                for order in active_orders:
                    if not is_own_order(order, user_id):
                        filtered_orders.append(order)
                
                if not filtered_orders:
                    await query.edit_message_text(
                        "✅ *Нет доступных активных заявок*\n\n"
                        "Ваши собственные заказы не отображаются в этом списке.",
                        reply_markup=get_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    keyboard_buttons = []
                    for order in filtered_orders[:10]:
                        formatted_code = format_code_for_display(order.get('order_code', 'НЕТ КОДА'))
                        ticket_type_emoji = "🎩" if order.get('ticket_type') == 'vip' else "🎟"
                        keyboard_buttons.append([
                            InlineKeyboardButton(
                                f"{ticket_type_emoji} {escape_markdown(str(order['user_name']))} - {formatted_code} - {order['total_amount']}₽", 
                                callback_data=f"view_order_{order['order_id']}"
                            )
                        ])
                    
                    keyboard_buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="promoter_menu")])
                    
                    await query.edit_message_text(
                        f"🟢 *Доступные активные заявки:* {len(filtered_orders)}\n\n"
                        "Ваши собственные заказы скрыты из этого списка.\n"
                        "Выберите заявку для обработки:",
                        reply_markup=InlineKeyboardMarkup(keyboard_buttons),
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                return PROMOTER_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "promoter_deferred":
            if user_id in PROMOTER_IDS:
                deferred_orders = db.get_orders_by_status("deferred")
                
                filtered_orders = []
                for order in deferred_orders:
                    if not is_own_order(order, user_id):
                        filtered_orders.append(order)
                
                if not filtered_orders:
                    await query.edit_message_text(
                        "✅ *Нет доступных отложенных заявки*\n\n"
                        "Ваши собственные заказы не отображаются в этом списке.",
                        reply_markup=get_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    keyboard_buttons = []
                    for order in filtered_orders[:10]:
                        formatted_code = format_code_for_display(order.get('order_code', 'НЕТ КОДА'))
                        ticket_type_emoji = "🎩" if order.get('ticket_type') == 'vip' else "🎟"
                        keyboard_buttons.append([
                            InlineKeyboardButton(
                                f"{ticket_type_emoji} {escape_markdown(str(order['user_name']))} - {formatted_code} - {order['total_amount']}₽", 
                                callback_data=f"activate_order_{order['order_id']}"
                            )
                        ])
                    
                    keyboard_buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="promoter_menu")])
                    
                    await query.edit_message_text(
                        f"⏳ *Доступные отложенные заявки:* {len(filtered_orders)}\n\n"
                        "Ваши собственные заказы скрыты из этого списка.\n"
                        "Выберите заявку для активации:",
                        reply_markup=InlineKeyboardMarkup(keyboard_buttons),
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                return PROMOTER_DEFERRED
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data.startswith("view_order_"):
            if user_id in PROMOTER_IDS:
                order_id = data.replace("view_order_", "")
                order = db.get_order(order_id)
                
                if order:
                    own_order = is_own_order(order, user_id)
                    text = format_order_details_for_promoter(order, own_order)
                    
                    try:
                        username_for_link = order['username'] if order['username'] and order['username'] != 'без username' and order['username'] != 'None' else None
                        await query.edit_message_text(
                            text,
                            reply_markup=get_order_actions_keyboard(order_id, order['user_id'], username_for_link, own_order),
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except BadRequest:
                        plain_text = text.replace('*', '').replace('_', '').replace('`', '')
                        await query.edit_message_text(
                            plain_text,
                            reply_markup=get_order_actions_keyboard(order_id, order['user_id'], username_for_link, own_order)
                        )
                    
                    return PROMOTER_VIEW_ORDER
                else:
                    await query.edit_message_text(
                        "❌ *Заказ не найден*",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return PROMOTER_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data.startswith("activate_order_"):
            if user_id in PROMOTER_IDS:
                order_id = data.replace("activate_order_", "")
                order = db.get_order(order_id)
                
                if order and is_own_order(order, user_id):
                    await query.edit_message_text(
                        "❌ *Вы не можете активировать свой собственный заказ!*\n\n"
                        "Пожалуйста, выберите другой заказ для обработки.",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return PROMOTER_MENU
                
                if db.update_order_status(order_id, "active", username):
                    await query.edit_message_text(
                        f"✅ *Заказ #{order_id} активирован!*\n\n"
                        f"Заявка перемещена в активные.",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await query.edit_message_text(
                        "❌ *Ошибка при активации заказа*",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                return PROMOTER_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data.startswith("close_order_"):
            if user_id in PROMOTER_IDS:
                order_id = data.replace("close_order_", "")
                order = db.get_order(order_id)
                
                if order and is_own_order(order, user_id):
                    await query.edit_message_text(
                        "❌ *Вы не можете закрыть свой собственный заказ!*\n\n"
                        "Пожалуйста, выберите другой заказ для обработки.",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return PROMOTER_MENU
                
                if db.update_order_status(order_id, "closed", username):
                    await send_channel_notification(context, order, username, "closed")
                    
                    await send_to_lists_channel(context, order, username)
                    
                    await send_order_notification_to_user(context, order, "closed", username)
                    
                    await query.edit_message_text(
                        f"✅ *Заказ #{order_id} успешно закрыт!*\n\n"
                        f"Уведомления отправлены:\n"
                        f"• В канал закрытых заявок\n"
                        f"• В канал со списками\n"
                        f"• Пользователю",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await query.edit_message_text(
                        "❌ *Ошибка при закрытии заказа*",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                return PROMOTER_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data.startswith("defer_order_"):
            if user_id in PROMOTER_IDS:
                order_id = data.replace("defer_order_", "")
                order = db.get_order(order_id)
                
                if order and is_own_order(order, user_id):
                    await query.edit_message_text(
                        "❌ *Вы не можете отложить свой собственный заказ!*\n\n"
                        "Пожалуйста, выберите другой заказ для обработки.",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return PROMOTER_MENU
                
                if db.update_order_status(order_id, "deferred", username):
                    await query.edit_message_text(
                        f"⏳ *Заказ #{order_id} отложен!*\n\n"
                        f"Заявка перемещена в раздел отложенных.",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await query.edit_message_text(
                        "❌ *Ошибка при откладывании заказа*",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                return PROMOTER_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data.startswith("refund_order_"):
            if user_id in PROMOTER_IDS:
                order_id = data.replace("refund_order_", "")
                order = db.get_order(order_id)
                
                if order and is_own_order(order, user_id):
                    await query.edit_message_text(
                        "❌ *Вы не можете оформить возврат на свой собственный заказ!*\n\n"
                        "Пожалуйста, выберите другой заказ для обработки.",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return PROMOTER_MENU
                
                if db.update_order_status(order_id, "refunded", username):
                    await send_channel_notification(context, order, username, "refunded")
                    
                    await send_order_notification_to_user(context, order, "refunded", username)
                    
                    await query.edit_message_text(
                        f"❌ *Возврат по заказу #{order_id} оформлен!*\n\n"
                        f"Уведомления отправлены в канал и пользователю.",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await query.edit_message_text(
                        "❌ *Ошибка при оформлении возврата*",
                        reply_markup=get_back_to_promoter_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                
                return PROMOTER_MENU
            else:
                await query.edit_message_text(
                    "❌ *У вас нет прав промоутера*",
                    reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                    parse_mode=ParseMode.MARKDOWN
                )
                return MAIN_MENU
        
        elif data == "change_role":
            await query.edit_message_text(
                "🔄 *Смена роли*\n\n"
                "Пожалуйста, выберите, как вы хотите войти:",
                reply_markup=get_role_selection_keyboard(user_id),
                parse_mode=ParseMode.MARKDOWN
            )
            return ROLE_SELECTION
        
        else:
            await query.edit_message_text(
                "❌ *Неизвестная команда*",
                reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                parse_mode=ParseMode.MARKDOWN
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Ошибка в обработчике кнопок: {e}")
        
        try:
            await query.edit_message_text(
                "❌ *Произошла ошибка*",
                reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            await query.message.reply_text(
                "❌ *Произошла ошибка*",
                reply_markup=get_main_menu_keyboard(context.user_data.get('user_role', 'user')),
                parse_mode=ParseMode.MARKDOWN
            )
        
        return MAIN_MENU

# ========== ОБРАБОТЧИКИ ТЕКСТОВЫХ СООБЩЕНИЙ ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    try:
        if 'in_buy_process' in context.user_data:
            if 'name' not in context.user_data:
                if len(text) < 2:
                    await update.message.reply_text(
                        "❌ *Имя слишком короткое*\n\n"
                        "Введите ваше имя и фамилию (например: Александр Иванов):",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_NAME
                
                context.user_data['name'] = text
                await update.message.reply_text(
                    "📧 *Введите ваш Email*\n\n"
                    "Например: example@gmail.com",
                    parse_mode=ParseMode.MARKDOWN
                )
                return BUY_EMAIL
                
            elif 'email' not in context.user_data:
                if not is_valid_email(text):
                    await update.message.reply_text(
                        "❌ *Некорректный Email*\n\n"
                        "Введите корректный адрес электронной почты (например: example@gmail.com):",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_EMAIL
                
                context.user_data['email'] = text
                
                group_size = context.user_data.get('group_size', 1)
                if group_size == 1:
                    context.user_data['guests'] = [context.user_data['name']]
                    
                    ticket_type = context.user_data.get('ticket_type', 'standard')
                    
                    await update.message.reply_text(
                        format_order_summary(
                            context.user_data['name'],
                            context.user_data['email'],
                            group_size,
                            context.user_data['guests'],
                            ticket_type
                        ),
                        reply_markup=get_confirmation_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_CONFIRM
                else:
                    context.user_data['guest_counter'] = 1
                    await update.message.reply_text(
                        f"👥 *Введите имя гостя #{1}*\n\n"
                        "Например: Мария Смирнова",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_GUESTS
                    
            elif 'guests' in context.user_data and 'guest_counter' in context.user_data:
                group_size = context.user_data.get('group_size', 1)
                guest_counter = context.user_data.get('guest_counter', 1)
                
                if len(text) < 2:
                    await update.message.reply_text(
                        "❌ *Имя слишком короткое*\n\n"
                        f"Введите имя гостя #{guest_counter} заново:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_GUESTS
                
                context.user_data['guests'].append(text)
                
                if guest_counter < group_size:
                    context.user_data['guest_counter'] = guest_counter + 1
                    await update.message.reply_text(
                        f"👥 *Введите имя гостя #{guest_counter + 1}*\n\n"
                        "Например: Алексей Петров",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_GUESTS
                else:
                    ticket_type = context.user_data.get('ticket_type', 'standard')
                    
                    await update.message.reply_text(
                        format_order_summary(
                            context.user_data['name'],
                            context.user_data['email'],
                            group_size,
                            context.user_data['guests'],
                            ticket_type
                        ),
                        reply_markup=get_confirmation_keyboard(),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_CONFIRM
        
        elif 'group_size' not in context.user_data and 'ticket_type' in context.user_data:
            if text.isdigit():
                group_size = int(text)
                if 1 <= group_size <= 100:
                    context.user_data['group_size'] = group_size
                    context.user_data['guests'] = []
                    
                    ticket_type = context.user_data.get('ticket_type', 'standard')
                    
                    await update.message.reply_text(
                        format_price_calculation(group_size, ticket_type) + "\n\n"
                        "👉 *Продолжить покупку?*",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Да, продолжить", callback_data="buy_continue")],
                            [InlineKeyboardButton("❌ Нет, отмена", callback_data="back_to_menu")]
                        ]),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_TICKET_TYPE
                else:
                    await update.message.reply_text(
                        "❌ *Некорректное количество*\n\n"
                        "Введите число от 1 до 100:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return BUY_TICKET_TYPE
        
        elif 'editing_key' in context.user_data:
            if user_id in ADMIN_IDS:
                editing_key = context.user_data['editing_key']
                editing_name = context.user_data.get('editing_name', 'настройки')
                
                if editing_key == 'event_info_text':
                    if event_settings.update_setting('event_info_text', text):
                        await update.message.reply_text(
                            f"✅ *Текст кнопки 'Событие' успешно обновлен!*\n\n"
                            f"Новый текст сохранен.\n\n"
                            f"Можно проверить, нажав кнопку 'Событие' в главном меню.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        
                        context.user_data.pop('editing_key', None)
                        context.user_data.pop('editing_name', None)
                        
                        await update.message.reply_text(
                            "⚡️ *Панель администратора*",
                            reply_markup=get_admin_keyboard(),
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_MENU
                    else:
                        await update.message.reply_text(
                            f"❌ *Ошибка при обновлении текста*",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_EDIT_TEXT
                
                elif editing_key == 'price_standard' or editing_key == 'price_group' or editing_key == 'price_vip':
                    if not text.isdigit():
                        await update.message.reply_text(
                            f"❌ *Некорректная цена*\n\n"
                            f"Введите цену цифрами (например: 1000):",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_EDIT_TEXT
                    value = int(text)
                    if value <= 0:
                        await update.message.reply_text(
                            f"❌ *Цена должна быть положительным числом*\n\n"
                            f"Введите корректную цену:",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_EDIT_TEXT
                
                elif editing_key == 'group_threshold':
                    if not text.isdigit():
                        await update.message.reply_text(
                            f"❌ *Некорректное число*\n\n"
                            f"Введите порог цифрами (например: 5):",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_EDIT_TEXT
                    value = int(text)
                    if value < 2:
                        await update.message.reply_text(
                            f"❌ *Порог должен быть не менее 2*\n\n"
                            f"Введите корректное значение:",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_EDIT_TEXT
                
                elif editing_key == 'contact_telegram':
                    value = text
                    if not (value.startswith('@') or value.startswith('https://t.me/')):
                        value = f"@{value.lstrip('@')}"
                
                else:
                    value = text
                
                if event_settings.update_setting(editing_key, value):
                    await update.message.reply_text(
                        f"✅ *{editing_name} успешно обновлена!*\n\n"
                        f"Новое значение: *{value}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    context.user_data.pop('editing_key', None)
                    context.user_data.pop('editing_name', None)
                    
                    if editing_key.startswith('price') or editing_key == 'group_threshold':
                        await update.message.reply_text(
                            "💰 *Редактирование цен*",
                            reply_markup=get_price_edit_keyboard(),
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_EDIT
                    elif editing_key.startswith('contact'):
                        await update.message.reply_text(
                            "📞 *Редактирование контактов*",
                            reply_markup=get_contacts_edit_keyboard(),
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ADMIN_EDIT
                else:
                    await update.message.reply_text(
                        f"❌ *Ошибка при обновлении {editing_name}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return ADMIN_EDIT_TEXT
        
        else:
            role = context.user_data.get('user_role', 'user')
            await update.message.reply_text(
                f"🏠 *Главное меню*\n\n"
                f"Выберите действие:",
                reply_markup=get_main_menu_keyboard(role),
                parse_mode=ParseMode.MARKDOWN
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Ошибка в обработчике текста: {e}")
        
        await update.message.reply_text(
            "❌ *Произошла ошибка*\n\n"
            "Пожалуйста, попробуйте еще раз.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        return MAIN_MENU

# ========== КОМАНДА ДЛЯ ОТПРАВКИ ЛОГОВ ==========
async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для отправки логов в канал"""
    try:
        user = update.effective_user
        
        if user.id in ADMIN_IDS:
            await update.message.reply_text(
                "📋 *Собираю логи...*",
                parse_mode=ParseMode.MARKDOWN
            )
            
            stats = db.get_statistics()
            
            recent_orders = []
            try:
                with closing(db.get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 10")
                    recent_orders = [dict(row) for row in cursor.fetchall()]
            except Exception as e:
                logger.error(f"Ошибка получения последних заказов: {e}")
            
            log_message = (
                "📊 *ЛОГИ БОТА*\n\n"
                f"*📅 Время:* {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"*👤 Администратор:* {user.username if user.username else user.id}\n\n"
                f"*📈 СТАТИСТИКА:*\n"
                f"• Всего заказов: {stats.get('total_orders', 0)}\n"
                f"• Активные: {stats.get('active_orders', 0)}\n"
                f"• Закрытые: {stats.get('closed_orders', 0)}\n"
                f"• Отложенные: {stats.get('deferred_orders', 0)}\n"
                f"• Возвраты: {stats.get('refunded_orders', 0)}\n"
                f"• Выручка: {stats.get('revenue', 0)} ₽\n"
                f"• Всего гостей: {stats.get('total_guests', 0)}\n\n"
            )
            
            if recent_orders:
                log_message += "*📋 ПОСЛЕДНИЕ 10 ЗАКАЗОВ:*\n"
                for order in recent_orders:
                    created_at = order['created_at']
                    if isinstance(created_at, str):
                        created_date = created_at[:16].replace('T', ' ')
                    else:
                        created_date = created_at.strftime('%d.%m.%Y %H:%M')
                    
                    log_message += (
                        f"• #{order['order_id']} | {order['status']} | "
                        f"{order['group_size']} чел. | {order['total_amount']} ₽ | "
                        f"{created_date}\n"
                    )
            
            await send_log_to_channel(context, f"Логи запрошены администратором {user.username if user.username else user.id}")
            
            await update.message.reply_text(
                log_message,
                parse_mode=ParseMode.MARKDOWN
            )
            
            await update.message.reply_text(
                "✅ *Логи отправлены в канал и отображены выше*",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ *У вас нет прав администратора*",
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Ошибка в команде logs: {e}")
        await update.message.reply_text(
            "❌ *Произошла ошибка при получении логов*",
            parse_mode=ParseMode.MARKDOWN
        )

# ========== ОБРАБОТЧИК КОМАНД ==========
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик команды /cancel"""
    user = update.effective_user
    
    context.user_data.pop('in_buy_process', None)
    context.user_data.pop('name', None)
    context.user_data.pop('email', None)
    context.user_data.pop('group_size', None)
    context.user_data.pop('guests', None)
    context.user_data.pop('guest_counter', None)
    context.user_data.pop('editing_key', None)
    context.user_data.pop('editing_name', None)
    context.user_data.pop('ticket_type', None)
    
    await update.message.reply_text(
        "❌ *Действие отменено*",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode=ParseMode.MARKDOWN
    )
    
    role = get_user_role(user.id)
    context.user_data['user_role'] = role
    
    await update.message.reply_text(
        f"🏠 *Главное меню*\n\n"
        f"Выберите действие:",
        reply_markup=get_main_menu_keyboard(role),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return MAIN_MENU

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    help_text = (
        "🎉 *SMILE PARTY Бот - Помощь*\n\n"
        "*Основные команды:*\n"
        "• /start - Начать работу с ботом\n"
        "• /help - Показать это сообщение\n"
        "• /cancel - Отменить текущее действие\n"
        "• /logs - Получить логи (только для администраторов)\n\n"
        "*Функции для всех:*\n"
        "• Узнать цены на билеты\n"
        "• Купить билеты онлайн\n"
        "• Просмотреть информацию о мероприятии\n"
        "• Посмотреть свои заказы\n\n"
        "*Для промоутеров:*\n"
        "• Просмотр активных заявок\n"
        "• Обработка заказов\n"
        "• Отслеживание статистики\n\n"
        "*Для администраторов:*\n"
        "• Управление настройками\n"
        "• Просмотр статистики\n"
        "• Редактирование информации о мероприятии\n"
        "• Получение логов\n\n"
        "*Техническая поддержка:* @smile_party"
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.MARKDOWN
    )

async def notify_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для отправки уведомлений всем пользователям"""
    user = update.effective_user
    
    if user.id in ADMIN_IDS:
        await update.message.reply_text(
            "🔄 *Начинаю отправку уведомлений о перезапуске...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        import threading
        thread = threading.Thread(target=send_restart_notifications)
        thread.start()
        
        await update.message.reply_text(
            "✅ *Запущена отправка уведомлений всем пользователям*\n\n"
            "Уведомления отправляются в фоновом режиме. Проверьте логи для деталей.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "❌ *У вас нет прав администратора*",
            parse_mode=ParseMode.MARKDOWN
        )

async def check_new_orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для ручной проверки новых заказов"""
    user = update.effective_user
    
    if user.id in ADMIN_IDS or user.id in PROMOTER_IDS:
        await update.message.reply_text(
            "🔄 *Проверяю новые заказы...*",
            parse_mode=ParseMode.MARKDOWN
        )
        
        unnotified_orders = db.get_unnotified_orders()
        
        if unnotified_orders:
            await update.message.reply_text(
                f"✅ *Найдено {len(unnotified_orders)} новых заказов*\n\n"
                "Отправляю уведомления...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            for order in unnotified_orders:
                await send_new_order_notification(context, order)
                await asyncio.sleep(1)
            
            await update.message.reply_text(
                f"✅ *Уведомления отправлены по {len(unnotified_orders)} заказам*",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "✅ *Нет новых заказов для уведомления*",
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await update.message.reply_text(
            "❌ *У вас нет прав для этой команды*",
            parse_mode=ParseMode.MARKDOWN
        )

# ========== ФУНКЦИЯ ДЛЯ ПЕРИОДИЧЕСКОЙ ПРОВЕРКИ НОВЫХ ЗАКАЗОВ ==========
async def periodic_notification_check(context: ContextTypes.DEFAULT_TYPE):
    """Периодическая проверка и отправка уведомлений о новых заказах"""
    await check_and_send_notifications(context)

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main() -> None:
    """Основная функция запуска бота"""
    db.reset_notification_status()
    
    application = ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(True).build()
    
    try:
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_repeating(periodic_notification_check, interval=30, first=10)
            logger.info("✅ Запущена периодическая проверка новых заказов")
        else:
            logger.warning("⚠️ JobQueue не доступен. Для периодических задач установите: pip install 'python-telegram-bot[job-queue]'")
    except Exception as e:
        logger.warning(f"⚠️ JobQueue не доступен: {e}")
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            ROLE_SELECTION: [CallbackQueryHandler(button_handler)],
            MAIN_MENU: [
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
            BUY_TICKET_TYPE: [
                CallbackQueryHandler(button_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
            BUY_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
            BUY_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
            BUY_GUESTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
            BUY_CONFIRM: [CallbackQueryHandler(button_handler)],
            ADMIN_MENU: [CallbackQueryHandler(button_handler)],
            PROMOTER_MENU: [CallbackQueryHandler(button_handler)],
            ADMIN_EDIT: [CallbackQueryHandler(button_handler)],
            ADMIN_EDIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
            ],
            PROMOTER_VIEW_ORDER: [CallbackQueryHandler(button_handler)],
            PROMOTER_DEFERRED: [CallbackQueryHandler(button_handler)],
            ADMIN_RESET_STATS: [CallbackQueryHandler(button_handler)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("start", start_command),
            CommandHandler("help", help_command),
            CommandHandler("notify_all", notify_all_command),
            CommandHandler("check_orders", check_new_orders_command),
            CommandHandler("logs", logs_command)
        ]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("notify_all", notify_all_command))
    application.add_handler(CommandHandler("check_orders", check_new_orders_command))
    application.add_handler(CommandHandler("logs", logs_command))
    
    logger.info("✅ Бот запущен и готов к работе!")
    
    import threading
    import time
    
    def send_notifications_delayed():
        time.sleep(5)
        logger.info("🔄 Начинаю отправку уведомлений о перезапуске...")
        send_restart_notifications()
    
    notification_thread = threading.Thread(target=send_notifications_delayed)
    notification_thread.daemon = True
    notification_thread.start()
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()