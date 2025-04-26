import os
import yaml
from typing import Dict, Any

def load_config(config_dir: str = None) -> Dict[str, Any]:
    """
    Load the YAML configuration file.
    
    Args:
        config_dir: Optional directory path where config.yaml is located.
                   If None, will look in ../config relative to this file.
    
    Returns:
        Dict containing the configuration
    """
    if config_dir is None:
        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config')
    
    config_path = os.path.join(config_dir, 'config.yaml')
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config

def get_config_value(config: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Safely get a value from the config dictionary using dot notation.
    
    Args:
        config: The configuration dictionary
        *keys: The keys to traverse
        default: Default value if key doesn't exist
    
    Returns:
        The value if found, otherwise the default
    """
    current = config
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current 