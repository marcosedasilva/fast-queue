from fastapi import Header, HTTPException
from firebase_admin import auth
import logging # Use o logging oficial, o Cloud Run prefere

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        # Log para quando o front esquece o token
        logging.error("❌ Token não enviado pelo Frontend")
        raise HTTPException(status_code=401, detail="Token não fornecido")
    
    token = authorization.split(" ")[1]
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        # ISSO VAI APARECER NO CLOUD RUN
        logging.error(f"🔥 ERRO NA VALIDAÇÃO DO TOKEN: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Erro interno: {str(e)}")