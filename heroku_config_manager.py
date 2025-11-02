import requests
import logging
from typing import Dict, Optional
from config import *

logger = logging.getLogger(__name__)

class HerokuConfigManager:
    def __init__(self):
        self.heroku_api_key = HEROKU_API_KEY
        self.heroku_app_name = HEROKU_APP_NAME
        self.base_url = "https://api.heroku.com"
        self.headers = {
            "Authorization": f"Bearer {self.heroku_api_key}",
            "Accept": "application/vnd.heroku+json; version=3",
            "Content-Type": "application/json"
        }
    
    def get_config_var(self, var_name: str) -> Optional[str]:
        """Получить значение конфигурационной переменной"""
        try:
            url = f"{self.base_url}/apps/{self.heroku_app_name}/config-vars"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            config_vars = response.json()
            return config_vars.get(var_name)
        except Exception as e:
            logger.error(f"Error getting config var {var_name}: {e}")
            return None
    
    def set_config_var(self, var_name: str, value: str) -> bool:
        """Установить значение конфигурационной переменной"""
        try:
            url = f"{self.base_url}/apps/{self.heroku_app_name}/config-vars"
            data = {var_name: value}
            response = requests.patch(url, json=data, headers=self.headers)
            response.raise_for_status()
            
            logger.info(f"Successfully updated {var_name} to {value}")
            return True
        except Exception as e:
            logger.error(f"Error setting config var {var_name}: {e}")
            return False
    
    def get_all_config_vars(self) -> Dict[str, str]:
        """Получить все конфигурационные переменные"""
        try:
            url = f"{self.base_url}/apps/{self.heroku_app_name}/config-vars"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            logger.error(f"Error getting all config vars: {e}")
            return {}

# Функции для управления Stripe режимом
def get_current_stripe_mode() -> str:
    """Получить текущий режим Stripe"""
    config_manager = HerokuConfigManager()
    current_value = config_manager.get_config_var('STRIPE_IS_TEST_MODE_ON')
    return "TEST" if current_value == 'True' else "LIVE"

def toggle_stripe_mode() -> tuple[bool, str]:
    """Переключить режим Stripe и вернуть (успех, новый_режим)"""
    config_manager = HerokuConfigManager()
    
    try:
        current_value = config_manager.get_config_var('STRIPE_IS_TEST_MODE_ON')
        new_value = 'False' if current_value == 'True' else 'True'
        
        success = config_manager.set_config_var('STRIPE_IS_TEST_MODE_ON', new_value)
        if success:
            new_mode = "TEST" if new_value == 'True' else "LIVE"
            return True, new_mode
        else:
            return False, "ERROR"
    except Exception as e:
        logger.error(f"Error toggling Stripe mode: {e}")
        return False, "ERROR"

def set_stripe_mode(test_mode: bool) -> tuple[bool, str]:
    """Установить конкретный режим Stripe"""
    config_manager = HerokuConfigManager()
    
    try:
        new_value = 'True' if test_mode else 'False'
        success = config_manager.set_config_var('STRIPE_IS_TEST_MODE_ON', new_value)
        
        if success:
            new_mode = "TEST" if test_mode else "LIVE"
            return True, new_mode
        else:
            return False, "ERROR"
    except Exception as e:
        logger.error(f"Error setting Stripe mode: {e}")
        return False, "ERROR"