import os
import shutil
from typing import Optional


def get_device_commands_path(device_name: Optional[str] = None) -> str:
    """Возвращает путь к файлу commands.json для устройства.
    
    Если файл в targets/<device>/commands.json не существует,
    создаёт папку и копирует файл из targets/commands.json.
    """
    base_dir = os.path.dirname(os.path.dirname(__file__))
    targets_dir = os.path.join(base_dir, "targets")
    default_commands = os.path.join(targets_dir, "commands.json")
    
    if device_name is None:
        return default_commands
    
    device_dir = os.path.join(targets_dir, device_name)
    device_commands = os.path.join(device_dir, "commands.json")
    
    if not os.path.exists(device_commands):
        os.makedirs(device_dir, exist_ok=True)
        if os.path.exists(default_commands):
            shutil.copy(default_commands, device_commands)
    
    return device_commands
