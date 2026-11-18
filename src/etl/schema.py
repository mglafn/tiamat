"""
src/etl/schema.py
-----------------
Shared DuckDB ENUM definitions used by both full ingestion and snapshot pruning.
"""

PRICE_ENUM_DDL = """
    CREATE OR REPLACE TYPE price_format AS ENUM ('paper', 'mtgo');
    CREATE OR REPLACE TYPE price_vendor AS ENUM (
        'tcgplayer',
        'cardkingdom',
        'cardmarket',
        'cardsphere',
        'starcitygames',
        'cardhoarder',
        'manapool'
    );
    CREATE OR REPLACE TYPE price_list_type AS ENUM ('retail', 'buylist');
    CREATE OR REPLACE TYPE price_finish AS ENUM ('normal', 'foil', 'etched');
"""
