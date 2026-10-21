"""
Clientes para APIs de validación externa.
- AbstractAPI: validación de correos electrónicos
- Google Maps Address Validation: normalización de direcciones
"""
import os
import requests
from flask import current_app
from functools import lru_cache


class AbstractAPIEmailValidator:
    """Cliente para AbstractAPI Email Validation."""
    
    BASE_URL = "https://api.abstractapi.com/v1/email_validation"
    
    def __init__(self, api_key=None):
        self.api_key = api_key or current_app.config.get("ABSTRACT_API_KEY")
        if not self.api_key:
            raise ValueError("Falta ABSTRACT_API_KEY en la configuración")
    
    def validar(self, email, timeout=10):
        """
        Valida un correo electrónico.
        
        Returns:
            dict con:
                - valido: bool
                - entregable: bool (DELIVERABLE)
                - formato_valido: bool
                - es_temporal: bool
                - es_gratis: bool
                - calidad: float (0-1)
                - sugerencia: str (si el correo tiene typo común)
                - detalle: dict (respuesta completa de la API)
        """
        if not self.api_key:
            return {"valido": False, "error": "API key no configurada"}
        
        try:
            params = {"api_key": self.api_key, "email": email}
            resp = requests.get(
                "https://api.abstractapi.com/v1/email_validation/",
                params=params,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            
            entregable = data.get("deliverability") == "DELIVERABLE"
            formato_ok = data.get("is_valid_format", {}).get("value", False)
            es_temporal = data.get("is_disposable_email", {}).get("value", False)
            es_gratis = data.get("is_free_email", {}).get("value", False)
            
            # Heurística simple de calidad
            calidad = 0.0
            if formato_ok: calidad += 0.3
            if entregable: calidad += 0.4
            if not es_temporal: calidad += 0.2
            if not es_gratis: calidad += 0.1
            
            return {
                "valido": formato_ok and entregable and not es_temporal,
                "entregable": entregable,
                "formato_valido": formato_ok,
                "es_temporal": es_temporal,
                "es_gratis": es_gratis,
                "calidad": round(calidad, 2),
                "sugerencia": data.get("autocorrect"),
                "detalle": data
            }
        except requests.RequestException as e:
            return {"valido": False, "error": f"Error de red: {e}"}
        except Exception as e:
            return {"valido": False, "error": f"Error inesperado: {e}"}


class GoogleAddressValidator:
    """Cliente para Google Maps Address Validation API."""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or current_app.config.get("GOOGLE_MAPS_API_KEY")
        if not self.api_key:
            raise ValueError("Falta GOOGLE_MAPS_API_KEY en la configuración")
    
    @lru_cache(maxsize=256)
    def validar(self, direccion, timeout=10):
        """
        Valida y normaliza una dirección.
        
        Returns:
            dict con:
                - valido: bool
                - direccion_normalizada: str
                - componentes: dict (calle, numero, ciudad, codigo_postal, pais)
                - coordenadas: (lat, lng)
                - confianza: float (0-1)
                - detalle: dict (respuesta completa)
        """
        if not self.api_key:
            return {"valido": False, "error": "API key no configurada"}
        
        try:
            url = f"https://addressvalidation.googleapis.com/v1:validateAddress?key={self.api_key}"
            payload = {
                "address": {
                    "addressLines": [direccion]
                },
                "enableUspsCass": False  # Solo para US; en otros países false
            }
            resp = requests.post(
                f"https://addressvalidation.googleapis.com/v1:validateAddress?key={self.api_key}",
                json=payload,
                timeout=timeout
            )
            resp.raise_for_status()
            data = resp.json()
            
            result = data.get("result", {})
            verdict = result.get("verdict", {})
            
            # Direccion normalizada
            address = result.get("address", {})
            address_lines = address.get("addressLines", [])
            direccion_normalizada = ", ".join(address_lines) if address_lines else direccion
            
            # Componentes
            components = address.get("addressComponents", {})
            componentes = {
                "calle": "",
                "numero": "",
                "ciudad": "",
                "codigo_postal": "",
                "pais": ""
            }
            for comp in components:
                types = comp.get("componentType", [])
                name = comp.get("componentName", {}).get("text", "")
                if "route" in types:
                    componentes["calle"] = name
                elif "street_number" in types:
                    componentes["numero"] = name
                elif "locality" in types:
                    componentes["ciudad"] = name
                elif "postal_code" in types:
                    componentes["codigo_postal"] = name
                elif "country" in types:
                    componentes["pais"] = name
            
            # Coordenadas
            geocode = result.get("geocode", {})
            location = geocode.get("location", {})
            coords = (location.get("latitude"), location.get("longitude")) if location else None
            
            # Confianza
            confianza = 0.0
            if verdict.get("hasUnconfirmedComponents", True) == False:
                confianza += 0.4
            if verdict.get("hasInferredComponents", True) == False:
                confianza += 0.3
            if verdict.get("addressComplete", False):
                confianza += 0.3
            
            return {
                "valido": verdict.get("inputGranularity") != "MISSING",
                "direccion_normalizada": direccion_normalizada,
                "componentes": componentes,
                "coordenadas": coords,
                "confianza": round(confianza, 2),
                "detalle": data
            }
        except requests.RequestException as e:
            return {"valido": False, "error": f"Error de red: {e}"}
        except Exception as e:
            return {"valido": False, "error": f"Error inesperado: {e}"}


# Instancias globales (se crean lazily)
_email_validator = None
_address_validator = None


def get_email_validator():
    global _email_validator
    if _email_validator is None:
        _email_validator = AbstractAPIEmailValidator()
    return _email_validator


def get_address_validator():
    global _address_validator
    if _address_validator is None:
        _address_validator = GoogleAddressValidator()
    return _address_validator