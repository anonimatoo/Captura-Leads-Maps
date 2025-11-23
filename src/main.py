"""
APIFY ACTOR: Caçador de Leads Locais (Google Maps Brasil Edition)
Autor: Clayton Silva
"""

import asyncio
import re
from apify import Actor
from playwright.async_api import async_playwright

# Nome do evento PPE (Pagamento por Evento) para leads validados
PPE_EVENT_VALIDADO = "CONTATO_VALIDADO_WHATSAPP_BR"

# --- LÓGICA DE NEGÓCIO BRASILEIRA ---
def process_brazilian_contact(phone_raw):
    """
    Limpa o telefone, classifica (Fixo/Celular) e gera link WhatsApp.
    O código assume que a string bruta já inclui o DDD.
    """
    if not phone_raw:
        return {"phone_clean": "N/A", "type": "N/A", "whatsapp_link": "N/A"}

    # Remove tudo que não é número
    numbers_only = re.sub(r'\D', '', phone_raw)
    
    contact_info = {"phone_clean": numbers_only, "type": "☎️ Fixo", "whatsapp_link": ""}

    # 11 dígitos = DDD (2) + 9 (1) + número (8)
    if len(numbers_only) == 11 and numbers_only[2] == '9':
        contact_info["type"] = "📱 Celular/WhatsApp"
        # O Apify não precisa do prefixo 55 se o número já tem o DDD, mas incluímos por segurança.
        contact_info["whatsapp_link"] = f"https://wa.me/55{numbers_only}"
    
    # 10 dígitos = DDD (2) + número (8)
    elif len(numbers_only) == 10:
         contact_info["type"] = "☎️ Fixo"
         
    else:
        # Se não tem 10 ou 11 dígitos, é inválido ou incompleto
        contact_info["type"] = "⚠️ Inválido"

    return contact_info

async def main():
    # Removido 'if __name__ == '__main__':', pois é desnecessário no Apify.
    async with Actor:
        actor_input = await Actor.get_input() or {}
        search_term = actor_input.get('search', 'Dentistas em Praia Grande, SP')
        max_items = actor_input.get('max_items', 10)
        
        Actor.log.info(f"🔎 Iniciando busca por: {search_term} (Alvo: {max_items} leads)")

        # Configuração de proxy robusta (o Apify trata a autenticação)
        proxy_configuration = await Actor.create_proxy_configuration(groups=['RESIDENTIAL'])

        async with async_playwright() as p:
            browser_args = {
                "headless": True,
                "args": ["--disable-blink-features=AutomationControlled"]
            }
            if proxy_configuration:
                proxy_url = await proxy_configuration.new_url()
                browser_args["proxy"] = {"server": proxy_url}

            browser = await p.chromium.launch(**browser_args)
            page = await browser.new_page()

            try:
                await page.goto("https://www.google.com/maps", timeout=60000)
                await page.wait_for_selector("input#searchboxinput")
                await page.locator("input#searchboxinput").fill(search_term)
                await page.keyboard.press("Enter")
                
                Actor.log.info("⏳ Aguardando e rolando resultados...")
                await page.wait_for_selector('div[role="feed"]', timeout=30000)

                # --- LÓGICA DE SCROLL INFINITO ---
                leads_scraped = 0
                feed_selector = 'div[role="feed"]'
                
                # Loop para garantir que o número mínimo de itens seja carregado
                while leads_scraped < max_items:
                    # Encontra o elemento de feed e rola o mouse (simulação humana)
                    await page.hover(feed_selector)
                    await page.mouse.wheel(0, 5000)
                    await asyncio.sleep(2)
                    
                    # Atualiza a contagem dos cards
                    cards = await page.locator(f'{feed_selector} > div > div[role="article"]').all()
                    current_count = len(cards)
                    Actor.log.info(f"📍 Total de cards carregados: {current_count}")
                    
                    if current_count >= max_items:
                        leads_scraped = current_count
                        break
                        
                    # Verifica se chegou ao fim da lista (texto de "Você chegou ao final...")
                    if await page.locator("text=Você chegou ao final da lista").count() > 0:
                        leads_scraped = current_count
                        Actor.log.warning("Fim da lista atingido antes de max_items.")
                        break
                    
                    leads_scraped = current_count # Atualiza a contagem para o próximo ciclo

                # --- EXTRAÇÃO E PROCESSAMENTO DE DADOS ---
                # Garante que processa apenas o número solicitado de itens
                final_cards_to_process = cards[:max_items]

                for i, card in enumerate(final_cards_to_process):
                    phone_raw = None
                    try:
                        # Extração da informação mais básica
                        text_content = await card.inner_text()
                        lines = text_content.split('\n')
                        name = lines[0] if lines else "Sem Nome"
                        
                        # Tenta encontrar o telefone no texto do card
                        phone_match = re.search(r'\(?\d{2}\)?\s?\d{4,5}-?\d{4}', text_content)
                        if phone_match:
                            phone_raw = phone_match.group(0)

                        br_data = process_brazilian_contact(phone_raw)
                        
                        # ⚠️ INTEGRAÇÃO PPE (Pagamento por Evento)
                        if br_data["type"] == "📱 Celular/WhatsApp":
                            # Envia o evento para cobrar US$ 0.08 pela validação do celular/WhatsApp
                            await Actor.add_event_data(PPE_EVENT_VALIDADO, 1)

                        lead_data = {
                            "Empresa": name, 
                            "Telefone_Bruto": phone_raw or "N/A", 
                            "Telefone_Limpo": br_data["phone_clean"],
                            "Tipo": br_data["type"], 
                            "WhatsApp_Link": br_data["whatsapp_link"], 
                            "Ranking": i + 1,
                            "Busca_Origem": search_term
                        }
                        
                        # Envia o item para o Dataset (Custo de US$ 0.02)
                        await Actor.push_data(lead_data)
                        
                    except Exception as e:
                        # Loga o erro, mas continua para o próximo card (robustez)
                        Actor.log.warning(f"Erro ao processar card {i+1} ({name}): {e}. Pulando.")
                        continue
                        
            except Exception as e:
                Actor.log.error(f"ERRO FATAL DE EXECUÇÃO: {e}")
            finally:
                await browser.close()
                Actor.log.info("Navegador fechado. Processo finalizado.")
                
