FROM apify/actor-python-playwright:3.11

COPY . ./

RUN pip install -r requirements.txt

CMD ["python3", "src/main.py"]
