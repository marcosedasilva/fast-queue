import httpx
import os

class AbacatePayService:
    def __init__(self):
        self.api_key = "abc_dev_SwCNRw00ZtmyMaX4AwZG6qsr" # Use .env em produção
        self.base_url = "https://api.abacatepay.com/v1"

    # services/payment-service/src/services/abacate_pay.py

    async def create_pix_billing(self, amount: float, external_id: str, user_email: str):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "amount": amount,
            "expiresIn": 300,
            "description": "Fast Queue",
            "metadata": {
                "externalId": external_id
            }
        }

        async with httpx.AsyncClient() as client:
            # Note: Verifique se a URL está correta. 
            # Algumas versões da API usam /billing e outras /billing/create
            response = await client.post(f"{self.base_url}/pixQrCode/create", json=payload, headers=headers)
            
            if response.status_code != 200:
                print(f"Erro AbacatePay: {response.text}")
                return None
            
            data = response.json()
            return {
                "data": data["data"]
            }