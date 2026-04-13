"""
Configuration module for VisInsp

This module provides functionality to read and manage configuration files.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """
    Configuration manager for VisInsp.
    
    Supports reading configuration from JSON files and provides
    easy access to configuration values.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_path: Path to the configuration file. If None, looks for
                        'config.json' in the project root.
        """
        self._config: Dict[str, Any] = {}
        self._config_path: Optional[Path] = None
        
        if config_path:
            self.load(config_path)
        else:
            # Try to find config.json in common locations
            self._try_default_locations()
    
    def _try_default_locations(self) -> None:
        """Try to load config from default locations."""
        possible_paths = [
            Path("config.json"),
            Path("config/config.json"),
            Path("../config.json"),
        ]
        
        for path in possible_paths:
            if path.exists():
                self.load(str(path))
                break
    
    def load(self, config_path: str) -> None:
        """
        Load configuration from a JSON file.
        
        Args:
            config_path: Path to the configuration file
            
        Raises:
            FileNotFoundError: If the config file doesn't exist
            json.JSONDecodeError: If the config file is not valid JSON
        """
        path = Path(config_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            self._config = json.load(f)
        
        self._config_path = path
        print(f"Configuration loaded from: {path.absolute()}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.
        
        Args:
            key: Configuration key (supports dot notation for nested values)
            default: Default value if key is not found
            
        Returns:
            Configuration value or default
            
        Example:
            config.get('database.host', 'localhost')
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value.
        
        Args:
            key: Configuration key (supports dot notation for nested values)
            value: Value to set
            
        Example:
            config.set('database.host', 'localhost')
        """
        keys = key.split('.')
        config = self._config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def save(self, config_path: Optional[str] = None) -> None:
        """
        Save configuration to a JSON file.
        
        Args:
            config_path: Path to save the configuration. If None, uses the
                        path from which config was loaded.
                        
        Raises:
            ValueError: If no config path is specified and no path was loaded
        """
        path = Path(config_path) if config_path else self._config_path
        
        if not path:
            raise ValueError("No configuration path specified")
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2)
        
        print(f"Configuration saved to: {path.absolute()}")
    
    def get_all(self) -> Dict[str, Any]:
        """
        Get all configuration values.
        
        Returns:
            Dictionary containing all configuration values
        """
        return self._config.copy()
    
    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access to config values."""
        return self.get(key)
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Allow dictionary-style setting of config values."""
        self.set(key, value)
    
    def __contains__(self, key: str) -> bool:
        """Check if a key exists in the configuration."""
        return self.get(key) is not None
    
    def __repr__(self) -> str:
        """String representation of the config."""
        return f"Config(path={self._config_path}, keys={list(self._config.keys())})"


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Convenience function to load configuration.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        Config object
    """
    return Config(config_path)

# Made with Bob
