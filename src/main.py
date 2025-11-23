import asyncio
import re
from apify import Actor
from playwright.async_api import async_playwright

def process_brazilian_contact(phone_raw):
    if not phone_raw:
        return {"phone_clean": "N/A", "type": "N/A", "whatsapp_link": "N/A"}

    numbers_only = re.sub(r'\D', '', phone_raw)
    contact_info = {"phone_clean": numbers_only, "type": "Indefinido", "whatsapp_link": ""}

    if len(numbers_only) >= 10 and len(numbers_only) <= 11:
        if len(numbers_only) == 10:
            contact_info["type"] = "☎️ Fixo"
        elif len(numbers_only) == 11 and numbers_only[2] == '9':
            contact_info["type"] = "📱 Celular/WhatsApp"
            contact_info["whatsapp_link"] = f"https://wa.me/55{numbers_only}"

    return contact_info

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        search_term = actor_input.get('search', 'Dentistas em Praia Grande, SP')
        max_items = actor_input.get('max_items', 10)
        Actor.log.info(f"🔎 Iniciando busca por: {search_term} (Alvo: {max_items} leads)")

        proxy_configuration = await Actor.create_proxy_configuration(groups=['RESIDENTIAL'])

        async with async_playwright() as p:
            browser_args = {"headless": True, "args": ["--disable-blink-features=AutomationControlled"]}
            if proxy_configuration:
                browser_args["proxy"] = {"server": await proxy_configuration.new_url(), "username": "", "password": ""}

            browser = await p.chromium.launch(**browser_args)
            page = await browser.new_page()

            try:
                await page.goto("https://www.google.com/maps", timeout=60000)
                await page.wait_for_selector("input#searchboxinput")
                await page.locator("input#searchboxinput").fill(search_term)
                await page.keyboard.press("Enter")
                Actor.log.info("⏳ Aguardando resultados...")
                await page.wait_for_selector('div[role="feed"]', timeout=30000)

                leads_scraped = 0
                feed_selector = 'div[role="feed"]'

                while leads_scraped < max_items:
                    cards = await page.locator(f'{feed_selector} > div > div[role="article"]').all()
                    current_count = len(cards)
                    Actor.log.info(f"📍 Carregados: {current_count}...")
                    await page.hover(feed_selector)
                    await page.mouse.wheel(0, 5000)
                    await asyncio.sleep(2)
                    if current_count >= max_items:
                        break
                    if await page.locator("text=Você chegou ao final da lista").count() > 0:
                        break

                final_leads = []
                cards = cards[:max_items]

                for i, card in enumerate(cards):
                    try:
                        text_content = await card.inner_text()
                        lines = text_content.split('\n')
                        name = lines[0] if lines else "Sem Nome"
                        phone_match = re.search(r'\(?\d{2}\)?\s?\d{4,5}-?\d{4}', text_content)
                        phone_raw = phone_match.group(0) if phone_match else None
                        br_data = process_brazilian_contact(phone_raw)
                        lead_data = {"Empresa": name, "Telefone": phone_raw or "N/A", "Tipo": br_data["type"], "WhatsApp": br_data["whatsapp_link"], "Ranking": i + 1}
                        await Actor.push_data(lead_data)
                    except Exception:
                        continue
            except Exception as e:
                Actor.log.error(f"Erro: {e}")
            finally:
                await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
