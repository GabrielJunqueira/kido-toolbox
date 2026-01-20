"""
Kido API Authentication Service
Handles multi-brand login logic for different countries
"""

import requests
from typing import Optional, Tuple


def get_brand_and_url(country_code: str) -> Tuple[str, str]:
    """
    Determine the brand and API URL based on country code.
    
    Args:
        country_code: Two-letter country code (e.g., 'br', 'es', 'pt')
        
    Returns:
        Tuple of (brand, root_url)
    """
    country_code = country_code.lower().strip()
    
    # Brand mapping based on country
    if country_code in ["es", "mx", "ch", "co", "pe"]:
        brand = "kido"
    elif country_code == "pt":
        brand = "altice"
    elif country_code == "pa":
        brand = "cw"
    elif country_code == "qa":
        brand = "ooredoo"
    else:
        # Default for br, ar, ecu, etc.
        brand = "claro"
    
    root_url = f"https://api.{brand}-{country_code}.kidodynamics.com/v1/"
    return brand, root_url


def login_kido(username: str, password: str, country_code: str) -> dict:
    """
    Authenticate with Kido Dynamics API.
    
    Args:
        username: User email
        password: User password
        country_code: Two-letter country code
        
    Returns:
        dict with token, root_url, and brand if successful, or error message
    """
    brand, root_url = get_brand_and_url(country_code)
    
    try:
        response = requests.post(
            root_url + "users/login",
            headers={
                'accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data=f'grant_type=password&username={username}&password={password}',
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            return {
                "success": True,
                "token": token,
                "root_url": root_url,
                "brand": brand,
                "country_code": country_code
            }
        else:
            return {
                "success": False,
                "error": f"Login failed ({response.status_code}): {response.text}"
            }
            
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Connection timeout. Please check your network and try again."
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Connection error: {str(e)}"
        }
