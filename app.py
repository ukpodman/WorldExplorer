"""World Explorer: country learning and a reusable geography challenge.

Country database adapted from mledoze/countries (ODbL 1.0).
Data and political records are separate from quiz generation and display.
Guest mode uses Streamlit and Pillow; optional account sign-in needs streamlit[auth].
"""
import json
import base64
import hashlib
import io
import urllib.request
import urllib.parse
import math
import random
import time
from collections import Counter
from datetime import date
from html import escape, unescape
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

st.set_page_config(page_title="World Explorer", layout="wide")

COUNTRIES = [{'id': 'ALB', 'name': 'Albania', 'continent': 'Europe', 'region': 'Southeast Europe', 'capitals': [{'name': 'Tirana', 'role': 'capital'}], 'currencies': [{'code': 'ALL', 'name': 'Albanian lek'}], 'languages': ['Albanian'], 'official_languages': ['Albanian'], 'borders': ['MNE', 'GRC', 'MKD', 'UNK'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'AND', 'name': 'Andorra', 'continent': 'Europe', 'region': 'Southern Europe', 'capitals': [{'name': 'Andorra la Vella', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Catalan'], 'official_languages': ['Catalan'], 'borders': ['FRA', 'ESP'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'ARG', 'name': 'Argentina', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Buenos Aires', 'role': 'capital'}], 'currencies': [{'code': 'ARS', 'name': 'Argentine peso'}], 'languages': ['Guaraní', 'Spanish'], 'official_languages': [], 'borders': ['BOL', 'BRA', 'CHL', 'PRY', 'URY'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'AUS', 'name': 'Australia', 'continent': 'Oceania', 'region': 'Australia and New Zealand', 'capitals': [{'name': 'Canberra', 'role': 'capital'}], 'currencies': [{'code': 'AUD', 'name': 'Australian dollar'}], 'languages': ['English'], 'official_languages': [], 'borders': [], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'BLZ', 'name': 'Belize', 'continent': 'North America', 'region': 'Central America', 'capitals': [{'name': 'Belmopan', 'role': 'capital'}], 'currencies': [{'code': 'BZD', 'name': 'Belize dollar'}], 'languages': ['Belizean Creole', 'English', 'Spanish'], 'official_languages': ['Belizean Creole', 'English', 'Spanish'], 'borders': ['GTM', 'MEX'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'BTN', 'name': 'Bhutan', 'continent': 'Asia', 'region': 'Southern Asia', 'capitals': [{'name': 'Thimphu', 'role': 'capital'}], 'currencies': [{'code': 'BTN', 'name': 'Bhutanese ngultrum'},
    {'code': 'INR', 'name': 'Indian rupee'}], 'languages': ['Dzongkha'], 'official_languages': ['Dzongkha'], 'borders': ['CHN', 'IND'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'BOL', 'name': 'Bolivia', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Sucre', 'role': 'constitutional capital'},
    {'name': 'La Paz', 'role': 'seat of government'}], 'currencies': [{'code': 'BOB', 'name': 'Bolivian boliviano'}], 'languages': ['Aymara', 'Guaraní', 'Quechua', 'Spanish'], 'official_languages': [], 'borders': ['ARG', 'BRA', 'CHL', 'PRY', 'PER'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'capital_source': 'https://tcpbolivia.bo/2026/07/12/', 'data_date': '2026-10-05'},
    {'id': 'BWA', 'name': 'Botswana', 'continent': 'Africa', 'region': 'Southern Africa', 'capitals': [{'name': 'Gaborone', 'role': 'capital'}], 'currencies': [{'code': 'BWP', 'name': 'Botswana pula'}], 'languages': ['English', 'Tswana'], 'official_languages': ['English'], 'borders': ['NAM', 'ZAF', 'ZMB', 'ZWE'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'BRA', 'name': 'Brazil', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Brasília', 'role': 'capital'}], 'currencies': [{'code': 'BRL', 'name': 'Brazilian real'}], 'languages': ['Portuguese'], 'official_languages': ['Portuguese'], 'borders': ['ARG', 'BOL', 'COL', 'GUF', 'GUY', 'PRY', 'PER', 'SUR', 'URY', 'VEN'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'KHM', 'name': 'Cambodia', 'continent': 'Asia', 'region': 'South-Eastern Asia', 'capitals': [{'name': 'Phnom Penh', 'role': 'capital'}], 'currencies': [{'code': 'KHR', 'name': 'Cambodian riel'},
    {'code': 'USD', 'name': 'United States dollar'}], 'languages': ['Khmer'], 'official_languages': ['Khmer'], 'borders': ['LAO', 'THA', 'VNM'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'CAN', 'name': 'Canada', 'continent': 'North America', 'region': 'North America', 'capitals': [{'name': 'Ottawa', 'role': 'capital'}], 'currencies': [{'code': 'CAD', 'name': 'Canadian dollar'}], 'languages': ['English', 'French'], 'official_languages': ['English', 'French'], 'borders': ['USA'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'CPV', 'name': 'Cape Verde', 'continent': 'Africa', 'region': 'Western Africa', 'capitals': [{'name': 'Praia', 'role': 'capital'}], 'currencies': [{'code': 'CVE', 'name': 'Cape Verdean escudo'}], 'languages': ['Portuguese'], 'official_languages': ['Portuguese'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'CHL', 'name': 'Chile', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Santiago', 'role': 'capital'}], 'currencies': [{'code': 'CLP', 'name': 'Chilean peso'}], 'languages': ['Spanish'], 'official_languages': [], 'borders': ['ARG', 'BOL', 'PER'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'CHN', 'name': 'China', 'continent': 'Asia', 'region': 'Eastern Asia', 'capitals': [{'name': 'Beijing', 'role': 'capital'}], 'currencies': [{'code': 'CNY', 'name': 'Chinese yuan'}], 'languages': ['Chinese'], 'official_languages': [], 'borders': ['AFG', 'BTN', 'MMR', 'HKG', 'IND', 'KAZ', 'NPL', 'PRK', 'KGZ', 'LAO', 'MAC', 'MNG', 'PAK', 'RUS', 'TJK', 'VNM'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'COL', 'name': 'Colombia', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Bogotá', 'role': 'capital'}], 'currencies': [{'code': 'COP', 'name': 'Colombian peso'}], 'languages': ['Spanish'], 'official_languages': ['Spanish'], 'borders': ['BRA', 'ECU', 'PAN', 'PER', 'VEN'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'COM', 'name': 'Comoros', 'continent': 'Africa', 'region': 'Eastern Africa', 'capitals': [{'name': 'Moroni', 'role': 'capital'}], 'currencies': [{'code': 'KMF', 'name': 'Comorian franc'}], 'languages': ['Arabic', 'French', 'Comorian'], 'official_languages': ['Arabic', 'French', 'Comorian'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'CRI', 'name': 'Costa Rica', 'continent': 'North America', 'region': 'Central America', 'capitals': [{'name': 'San José', 'role': 'capital'}], 'currencies': [{'code': 'CRC', 'name': 'Costa Rican colón'}], 'languages': ['Spanish'], 'official_languages': ['Spanish'], 'borders': ['NIC', 'PAN'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'CUB', 'name': 'Cuba', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': 'Havana', 'role': 'capital'}], 'currencies': [{'code': 'CUC', 'name': 'Cuban convertible peso'},
    {'code': 'CUP', 'name': 'Cuban peso'}], 'languages': ['Spanish'], 'official_languages': ['Spanish'], 'borders': [], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'DMA', 'name': 'Dominica', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': 'Roseau', 'role': 'capital'}], 'currencies': [{'code': 'XCD', 'name': 'Eastern Caribbean dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'EGY', 'name': 'Egypt', 'continent': 'Africa', 'region': 'Northern Africa', 'capitals': [{'name': 'Cairo', 'role': 'capital'}], 'currencies': [{'code': 'EGP', 'name': 'Egyptian pound'}], 'languages': ['Arabic'], 'official_languages': ['Arabic'], 'borders': ['ISR', 'LBY', 'PSE', 'SDN'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'EST', 'name': 'Estonia', 'continent': 'Europe', 'region': 'Northern Europe', 'capitals': [{'name': 'Tallinn', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Estonian'], 'official_languages': ['Estonian'], 'borders': ['LVA', 'RUS'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'SWZ', 'name': 'Eswatini', 'continent': 'Africa', 'region': 'Southern Africa', 'capitals': [{'name': 'Mbabane', 'role': 'administrative capital'},
    {'name': 'Lobamba', 'role': 'royal and legislative capital'}], 'currencies': [{'code': 'SZL', 'name': 'Swazi lilangeni'},
    {'code': 'ZAR', 'name': 'South African rand'}], 'languages': ['English', 'Swazi'], 'official_languages': ['English', 'Swazi'], 'borders': ['MOZ', 'ZAF'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'capital_source': 'https://www.sadc.int/member-states/kingdom-eswatini', 'data_date': '2026-10-05'},
    {'id': 'FJI', 'name': 'Fiji', 'continent': 'Oceania', 'region': 'Melanesia', 'capitals': [{'name': 'Suva', 'role': 'capital'}], 'currencies': [{'code': 'FJD', 'name': 'Fijian dollar'}], 'languages': ['English', 'Fijian', 'Fiji Hindi'], 'official_languages': ['English', 'Fijian', 'Fiji Hindi'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'FRA', 'name': 'France', 'continent': 'Europe', 'region': 'Western Europe', 'capitals': [{'name': 'Paris', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['French'], 'official_languages': ['French'], 'borders': ['AND', 'BEL', 'DEU', 'ITA', 'LUX', 'MCO', 'ESP', 'CHE'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'DEU', 'name': 'Germany', 'continent': 'Europe', 'region': 'Western Europe', 'capitals': [{'name': 'Berlin', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['German'], 'official_languages': ['German'], 'borders': ['AUT', 'BEL', 'CZE', 'DNK', 'FRA', 'LUX', 'NLD', 'POL', 'CHE'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'GHA', 'name': 'Ghana', 'continent': 'Africa', 'region': 'Western Africa', 'capitals': [{'name': 'Accra', 'role': 'capital'}], 'currencies': [{'code': 'GHS', 'name': 'Ghanaian cedi'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': ['BFA', 'CIV', 'TGO'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'GRD', 'name': 'Grenada', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': "St. George's", 'role': 'capital'}], 'currencies': [{'code': 'XCD', 'name': 'Eastern Caribbean dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'GTM', 'name': 'Guatemala', 'continent': 'North America', 'region': 'Central America', 'capitals': [{'name': 'Guatemala City', 'role': 'capital'}], 'currencies': [{'code': 'GTQ', 'name': 'Guatemalan quetzal'}], 'languages': ['Spanish'], 'official_languages': ['Spanish'], 'borders': ['BLZ', 'SLV', 'HND', 'MEX'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'GUY', 'name': 'Guyana', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Georgetown', 'role': 'capital'}], 'currencies': [{'code': 'GYD', 'name': 'Guyanese dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': ['BRA', 'SUR', 'VEN'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'HND', 'name': 'Honduras', 'continent': 'North America', 'region': 'Central America', 'capitals': [{'name': 'Tegucigalpa', 'role': 'capital'}], 'currencies': [{'code': 'HNL', 'name': 'Honduran lempira'}], 'languages': ['Spanish'], 'official_languages': ['Spanish'], 'borders': ['GTM', 'SLV', 'NIC'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'IND', 'name': 'India', 'continent': 'Asia', 'region': 'Southern Asia', 'capitals': [{'name': 'New Delhi', 'role': 'capital'}], 'currencies': [{'code': 'INR', 'name': 'Indian rupee'}], 'languages': ['English', 'Hindi', 'Tamil'], 'official_languages': [], 'borders': ['BGD', 'BTN', 'MMR', 'CHN', 'NPL', 'PAK'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'ITA', 'name': 'Italy', 'continent': 'Europe', 'region': 'Southern Europe', 'capitals': [{'name': 'Rome', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Italian'], 'official_languages': ['Italian'], 'borders': ['AUT', 'FRA', 'SMR', 'SVN', 'CHE', 'VAT'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'JAM', 'name': 'Jamaica', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': 'Kingston', 'role': 'capital'}], 'currencies': [{'code': 'JMD', 'name': 'Jamaican dollar'}], 'languages': ['English', 'Jamaican Patois'], 'official_languages': ['English', 'Jamaican Patois'], 'borders': [], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'JPN', 'name': 'Japan', 'continent': 'Asia', 'region': 'Eastern Asia', 'capitals': [{'name': 'Tokyo', 'role': 'capital'}], 'currencies': [{'code': 'JPY', 'name': 'Japanese yen'}], 'languages': ['Japanese'], 'official_languages': [], 'borders': [], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'KEN', 'name': 'Kenya', 'continent': 'Africa', 'region': 'Eastern Africa', 'capitals': [{'name': 'Nairobi', 'role': 'capital'}], 'currencies': [{'code': 'KES', 'name': 'Kenyan shilling'}], 'languages': ['English', 'Swahili'], 'official_languages': ['English', 'Swahili'], 'borders': ['ETH', 'SOM', 'SSD', 'TZA', 'UGA'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'KIR', 'name': 'Kiribati', 'continent': 'Oceania', 'region': 'Micronesia', 'capitals': [{'name': 'South Tarawa', 'role': 'capital'}], 'currencies': [{'code': 'AUD', 'name': 'Australian dollar'},
    {'code': 'KID', 'name': 'Kiribati dollar'}], 'languages': ['English', 'Gilbertese'], 'official_languages': ['English', 'Gilbertese'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LAO', 'name': 'Laos', 'continent': 'Asia', 'region': 'South-Eastern Asia', 'capitals': [{'name': 'Vientiane', 'role': 'capital'}], 'currencies': [{'code': 'LAK', 'name': 'Lao kip'}], 'languages': ['Lao'], 'official_languages': ['Lao'], 'borders': ['MMR', 'KHM', 'CHN', 'THA', 'VNM'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LVA', 'name': 'Latvia', 'continent': 'Europe', 'region': 'Northern Europe', 'capitals': [{'name': 'Riga', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Latvian'], 'official_languages': ['Latvian'], 'borders': ['BLR', 'EST', 'LTU', 'RUS'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LSO', 'name': 'Lesotho', 'continent': 'Africa', 'region': 'Southern Africa', 'capitals': [{'name': 'Maseru', 'role': 'capital'}], 'currencies': [{'code': 'LSL', 'name': 'Lesotho loti'},
    {'code': 'ZAR', 'name': 'South African rand'}], 'languages': ['English', 'Sotho'], 'official_languages': ['English', 'Sotho'], 'borders': ['ZAF'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LIE', 'name': 'Liechtenstein', 'continent': 'Europe', 'region': 'Western Europe', 'capitals': [{'name': 'Vaduz', 'role': 'capital'}], 'currencies': [{'code': 'CHF', 'name': 'Swiss franc'}], 'languages': ['German'], 'official_languages': ['German'], 'borders': ['AUT', 'CHE'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LTU', 'name': 'Lithuania', 'continent': 'Europe', 'region': 'Northern Europe', 'capitals': [{'name': 'Vilnius', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Lithuanian'], 'official_languages': ['Lithuanian'], 'borders': ['BLR', 'LVA', 'POL', 'RUS'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LUX', 'name': 'Luxembourg', 'continent': 'Europe', 'region': 'Western Europe', 'capitals': [{'name': 'Luxembourg', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['German', 'French', 'Luxembourgish'], 'official_languages': ['German', 'French', 'Luxembourgish'], 'borders': ['BEL', 'FRA', 'DEU'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MDG', 'name': 'Madagascar', 'continent': 'Africa', 'region': 'Eastern Africa', 'capitals': [{'name': 'Antananarivo', 'role': 'capital'}], 'currencies': [{'code': 'MGA', 'name': 'Malagasy ariary'}], 'languages': ['French', 'Malagasy'], 'official_languages': ['French', 'Malagasy'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MDV', 'name': 'Maldives', 'continent': 'Asia', 'region': 'Southern Asia', 'capitals': [{'name': 'Malé', 'role': 'capital'}], 'currencies': [{'code': 'MVR', 'name': 'Maldivian rufiyaa'}], 'languages': ['Maldivian'], 'official_languages': ['Maldivian'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MLT', 'name': 'Malta', 'continent': 'Europe', 'region': 'Southern Europe', 'capitals': [{'name': 'Valletta', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['English', 'Maltese'], 'official_languages': ['English', 'Maltese'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MHL', 'name': 'Marshall Islands', 'continent': 'Oceania', 'region': 'Micronesia', 'capitals': [{'name': 'Majuro', 'role': 'capital'}], 'currencies': [{'code': 'USD', 'name': 'United States dollar'}], 'languages': ['English', 'Marshallese'], 'official_languages': ['English', 'Marshallese'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MUS', 'name': 'Mauritius', 'continent': 'Africa', 'region': 'Eastern Africa', 'capitals': [{'name': 'Port Louis', 'role': 'capital'}], 'currencies': [{'code': 'MUR', 'name': 'Mauritian rupee'}], 'languages': ['English', 'French', 'Mauritian Creole'], 'official_languages': [], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MEX', 'name': 'Mexico', 'continent': 'North America', 'region': 'North America', 'capitals': [{'name': 'Mexico City', 'role': 'capital'}], 'currencies': [{'code': 'MXN', 'name': 'Mexican peso'}], 'languages': ['Spanish'], 'official_languages': [], 'borders': ['BLZ', 'GTM', 'USA'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'FSM', 'name': 'Micronesia', 'continent': 'Oceania', 'region': 'Micronesia', 'capitals': [{'name': 'Palikir', 'role': 'capital'}], 'currencies': [], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MDA', 'name': 'Moldova', 'continent': 'Europe', 'region': 'Eastern Europe', 'capitals': [{'name': 'Chișinău', 'role': 'capital'}], 'currencies': [{'code': 'MDL', 'name': 'Moldovan leu'}], 'languages': ['Romanian'], 'official_languages': ['Romanian'], 'borders': ['ROU', 'UKR'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MNG', 'name': 'Mongolia', 'continent': 'Asia', 'region': 'Eastern Asia', 'capitals': [{'name': 'Ulan Bator', 'role': 'capital'}], 'currencies': [{'code': 'MNT', 'name': 'Mongolian tögrög'}], 'languages': ['Mongolian'], 'official_languages': ['Mongolian'], 'borders': ['CHN', 'RUS'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'NAM', 'name': 'Namibia', 'continent': 'Africa', 'region': 'Southern Africa', 'capitals': [{'name': 'Windhoek', 'role': 'capital'}], 'currencies': [{'code': 'NAD', 'name': 'Namibian dollar'},
    {'code': 'ZAR', 'name': 'South African rand'}], 'languages': ['Afrikaans', 'German', 'English', 'Herero', 'Khoekhoe', 'Kwangali', 'Lozi', 'Ndonga', 'Tswana'], 'official_languages': ['Afrikaans', 'German', 'English', 'Herero', 'Khoekhoe', 'Kwangali', 'Lozi', 'Ndonga', 'Tswana'], 'borders': ['AGO', 'BWA', 'ZAF', 'ZMB'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'NPL', 'name': 'Nepal', 'continent': 'Asia', 'region': 'Southern Asia', 'capitals': [{'name': 'Kathmandu', 'role': 'capital'}], 'currencies': [{'code': 'NPR', 'name': 'Nepalese rupee'}], 'languages': ['Nepali'], 'official_languages': ['Nepali'], 'borders': ['CHN', 'IND'], 'landlocked': True, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'NZL', 'name': 'New Zealand', 'continent': 'Oceania', 'region': 'Australia and New Zealand', 'capitals': [{'name': 'Wellington', 'role': 'capital'}], 'currencies': [{'code': 'NZD', 'name': 'New Zealand dollar'}], 'languages': ['English', 'Māori', 'New Zealand Sign Language'], 'official_languages': ['Māori', 'New Zealand Sign Language'], 'borders': [], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'NIC', 'name': 'Nicaragua', 'continent': 'North America', 'region': 'Central America', 'capitals': [{'name': 'Managua', 'role': 'capital'}], 'currencies': [{'code': 'NIO', 'name': 'Nicaraguan córdoba'}], 'languages': ['Spanish'], 'official_languages': ['Spanish'], 'borders': ['CRI', 'HND'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'NGA', 'name': 'Nigeria', 'continent': 'Africa', 'region': 'Western Africa', 'capitals': [{'name': 'Abuja', 'role': 'capital'}], 'currencies': [{'code': 'NGN', 'name': 'Nigerian naira'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': ['BEN', 'CMR', 'TCD', 'NER'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'MKD', 'name': 'North Macedonia', 'continent': 'Europe', 'region': 'Southeast Europe', 'capitals': [{'name': 'Skopje', 'role': 'capital'}], 'currencies': [{'code': 'MKD', 'name': 'denar'}], 'languages': ['Macedonian'], 'official_languages': ['Macedonian'], 'borders': ['ALB', 'BGR', 'GRC', 'UNK', 'SRB'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'PLW', 'name': 'Palau', 'continent': 'Oceania', 'region': 'Micronesia', 'capitals': [{'name': 'Ngerulmud', 'role': 'capital'}], 'currencies': [{'code': 'USD', 'name': 'United States dollar'}], 'languages': ['English', 'Palauan'], 'official_languages': ['English', 'Palauan'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'PNG', 'name': 'Papua New Guinea', 'continent': 'Oceania', 'region': 'Melanesia', 'capitals': [{'name': 'Port Moresby', 'role': 'capital'}], 'currencies': [{'code': 'PGK', 'name': 'Papua New Guinean kina'}], 'languages': ['English', 'Hiri Motu', 'Tok Pisin'], 'official_languages': [], 'borders': ['IDN'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'PRY', 'name': 'Paraguay', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Asunción', 'role': 'capital'}], 'currencies': [{'code': 'PYG', 'name': 'Paraguayan guaraní'}], 'languages': ['Guaraní', 'Spanish'], 'official_languages': ['Guaraní', 'Spanish'], 'borders': ['ARG', 'BOL', 'BRA'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'PER', 'name': 'Peru', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Lima', 'role': 'capital'}], 'currencies': [{'code': 'PEN', 'name': 'Peruvian sol'}], 'languages': ['Aymara', 'Quechua', 'Spanish'], 'official_languages': ['Aymara', 'Quechua', 'Spanish'], 'borders': ['BOL', 'BRA', 'CHL', 'COL', 'ECU'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'PRT', 'name': 'Portugal', 'continent': 'Europe', 'region': 'Southern Europe', 'capitals': [{'name': 'Lisbon', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Portuguese'], 'official_languages': ['Portuguese'], 'borders': ['ESP'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'KNA', 'name': 'Saint Kitts and Nevis', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': 'Basseterre', 'role': 'capital'}], 'currencies': [{'code': 'XCD', 'name': 'Eastern Caribbean dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LCA', 'name': 'Saint Lucia', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': 'Castries', 'role': 'capital'}], 'currencies': [{'code': 'XCD', 'name': 'Eastern Caribbean dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'VCT', 'name': 'Saint Vincent and the Grenadines', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': 'Kingstown', 'role': 'capital'}], 'currencies': [{'code': 'XCD', 'name': 'Eastern Caribbean dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'WSM', 'name': 'Samoa', 'continent': 'Oceania', 'region': 'Polynesia', 'capitals': [{'name': 'Apia', 'role': 'capital'}], 'currencies': [{'code': 'WST', 'name': 'Samoan tālā'}], 'languages': ['English', 'Samoan'], 'official_languages': ['English', 'Samoan'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'SMR', 'name': 'San Marino', 'continent': 'Europe', 'region': 'Southern Europe', 'capitals': [{'name': 'City of San Marino', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Italian'], 'official_languages': ['Italian'], 'borders': ['ITA'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'SEN', 'name': 'Senegal', 'continent': 'Africa', 'region': 'Western Africa', 'capitals': [{'name': 'Dakar', 'role': 'capital'}], 'currencies': [{'code': 'XOF', 'name': 'West African CFA franc'}], 'languages': ['French'], 'official_languages': ['French'], 'borders': ['GMB', 'GIN', 'GNB', 'MLI', 'MRT'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'SYC', 'name': 'Seychelles', 'continent': 'Africa', 'region': 'Eastern Africa', 'capitals': [{'name': 'Victoria', 'role': 'capital'}], 'currencies': [{'code': 'SCR', 'name': 'Seychellois rupee'}], 'languages': ['Seychellois Creole', 'English', 'French'], 'official_languages': ['Seychellois Creole', 'English', 'French'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'SVN', 'name': 'Slovenia', 'continent': 'Europe', 'region': 'Central Europe', 'capitals': [{'name': 'Ljubljana', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Slovene'], 'official_languages': ['Slovene'], 'borders': ['AUT', 'HRV', 'ITA', 'HUN'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'SLB', 'name': 'Solomon Islands', 'continent': 'Oceania', 'region': 'Melanesia', 'capitals': [{'name': 'Honiara', 'role': 'capital'}], 'currencies': [{'code': 'SBD', 'name': 'Solomon Islands dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'ESP', 'name': 'Spain', 'continent': 'Europe', 'region': 'Southern Europe', 'capitals': [{'name': 'Madrid', 'role': 'capital'}], 'currencies': [{'code': 'EUR', 'name': 'Euro'}], 'languages': ['Spanish'], 'official_languages': ['Spanish'], 'borders': ['AND', 'FRA', 'GIB', 'PRT', 'MAR'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'LKA', 'name': 'Sri Lanka', 'continent': 'Asia', 'region': 'Southern Asia', 'capitals': [{'name': 'Sri Jayewardenepura Kotte', 'role': 'administrative capital'},
    {'name': 'Colombo', 'role': 'commercial capital'}], 'currencies': [{'code': 'LKR', 'name': 'Sri Lankan rupee'}], 'languages': ['Sinhala', 'Tamil'], 'official_languages': ['Sinhala', 'Tamil'], 'borders': ['IND'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'capital_source': 'https://www.mfa.gov.lk/en/national-profile-and-geography', 'data_date': '2026-10-05'},
    {'id': 'SUR', 'name': 'Suriname', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Paramaribo', 'role': 'capital'}], 'currencies': [{'code': 'SRD', 'name': 'Surinamese dollar'}], 'languages': ['Dutch'], 'official_languages': ['Dutch'], 'borders': ['BRA', 'GUF', 'GUY'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'STP', 'name': 'São Tomé and Príncipe', 'continent': 'Africa', 'region': 'Middle Africa', 'capitals': [{'name': 'São Tomé', 'role': 'capital'}], 'currencies': [{'code': 'STN', 'name': 'São Tomé and Príncipe dobra'}], 'languages': ['Portuguese'], 'official_languages': ['Portuguese'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'THA', 'name': 'Thailand', 'continent': 'Asia', 'region': 'South-Eastern Asia', 'capitals': [{'name': 'Bangkok', 'role': 'capital'}], 'currencies': [{'code': 'THB', 'name': 'Thai baht'}], 'languages': ['Thai'], 'official_languages': ['Thai'], 'borders': ['MMR', 'KHM', 'LAO', 'MYS'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'TLS', 'name': 'Timor-Leste', 'continent': 'Asia', 'region': 'South-Eastern Asia', 'capitals': [{'name': 'Dili', 'role': 'capital'}], 'currencies': [{'code': 'USD', 'name': 'United States dollar'}], 'languages': ['Portuguese', 'Tetum'], 'official_languages': ['Portuguese', 'Tetum'], 'borders': ['IDN'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'TON', 'name': 'Tonga', 'continent': 'Oceania', 'region': 'Polynesia', 'capitals': [{'name': "Nuku'alofa", 'role': 'capital'}], 'currencies': [{'code': 'TOP', 'name': 'Tongan paʻanga'}], 'languages': ['English', 'Tongan'], 'official_languages': ['English', 'Tongan'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'TTO', 'name': 'Trinidad and Tobago', 'continent': 'North America', 'region': 'Caribbean', 'capitals': [{'name': 'Port of Spain', 'role': 'capital'}], 'currencies': [{'code': 'TTD', 'name': 'Trinidad and Tobago dollar'}], 'languages': ['English'], 'official_languages': ['English'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'TUV', 'name': 'Tuvalu', 'continent': 'Oceania', 'region': 'Polynesia', 'capitals': [{'name': 'Funafuti', 'role': 'capital'}], 'currencies': [{'code': 'AUD', 'name': 'Australian dollar'},
    {'code': 'TVD', 'name': 'Tuvaluan dollar'}], 'languages': ['English', 'Tuvaluan'], 'official_languages': ['English', 'Tuvaluan'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'USA', 'name': 'United States', 'continent': 'North America', 'region': 'North America', 'capitals': [{'name': 'Washington D.C.', 'role': 'capital'}], 'currencies': [{'code': 'USD', 'name': 'United States dollar'}], 'languages': ['English'], 'official_languages': [], 'borders': ['CAN', 'MEX'], 'landlocked': False, 'tier': 1, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'URY', 'name': 'Uruguay', 'continent': 'South America', 'region': 'South America', 'capitals': [{'name': 'Montevideo', 'role': 'capital'}], 'currencies': [{'code': 'UYU', 'name': 'Uruguayan peso'}], 'languages': ['Spanish'], 'official_languages': [], 'borders': ['ARG', 'BRA'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'},
    {'id': 'VUT', 'name': 'Vanuatu', 'continent': 'Oceania', 'region': 'Melanesia', 'capitals': [{'name': 'Port Vila', 'role': 'capital'}], 'currencies': [{'code': 'VUV', 'name': 'Vanuatu vatu'}], 'languages': ['Bislama', 'English', 'French'], 'official_languages': ['Bislama', 'English', 'French'], 'borders': [], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://www.un.int/vanuatu/vanuatu/country-facts', 'data_date': '2026-10-05'},
    {'id': 'VNM', 'name': 'Vietnam', 'continent': 'Asia', 'region': 'South-Eastern Asia', 'capitals': [{'name': 'Hanoi', 'role': 'capital'}], 'currencies': [{'code': 'VND', 'name': 'Vietnamese đồng'}], 'languages': ['Vietnamese'], 'official_languages': ['Vietnamese'], 'borders': ['KHM', 'CHN', 'LAO'], 'landlocked': False, 'tier': 2, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-05'}]

# Update political records separately; never guess missing or stale leaders.
HEADS_OF_STATE = {'FRA': {'names': ['Emmanuel Macron'], 'title': 'President', 'verified_on': '2026-10-05', 'source': 'https://www.elysee.fr/emmanuel-macron.fr'},
    'NGA': {'names': ['Bola Ahmed Tinubu'], 'title': 'President', 'verified_on': '2026-10-05', 'source': 'https://statehouse.gov.ng/team/bola-ahmed-tinubu/'},
    'IND': {'names': ['Droupadi Murmu'], 'title': 'President', 'verified_on': '2026-10-05', 'source': 'https://www.presidentofindia.gov.in/'},
    'KEN': {'names': ['William Ruto'], 'title': 'President', 'verified_on': '2026-10-05', 'source': 'https://www.president.go.ke/administration/office-of-the-president/'},
    'ITA': {'names': ['Sergio Mattarella'], 'title': 'President', 'verified_on': '2026-10-05', 'source': 'https://www.quirinale.it/'},
    'DEU': {'names': ['Frank-Walter Steinmeier'], 'title': 'Federal President', 'verified_on': '2026-10-05', 'source': 'https://www.bundespraesident.de/EN/federal-president/frank-walter-steinmeier_node.html'},
    'CAN': {'names': ['Charles III'], 'title': 'King', 'verified_on': '2026-10-05', 'source': 'https://www.canada.ca/en/canadian-heritage/services/crown-canada/about.html'},
    'NZL': {'names': ['Charles III'], 'title': 'King', 'verified_on': '2026-10-05', 'source': 'https://gg.govt.nz/office-governor-general/roles-and-functions-governor-general/constitutional-role/constitution/constitution'},
    'BTN': {'names': ['Jigme Khesar Namgyel Wangchuck'], 'title': 'King', 'verified_on': '2026-10-05', 'source': 'https://www.mfa.gov.bt/rbecanberra/ambassador/'}}

# Presentation uses native Streamlit widgets; no external fonts or image downloads.
st.markdown("""
<style>
:root { --ink:#142b3a; --muted:#536978; --navy:#102d40; --teal:#087e83; --gold:#e4b65c; }
.stApp { background:radial-gradient(ellipse at 0% 10%,#e1f1ed 0,transparent 48%),#f4f6f8; color:var(--ink); }
.stApp .block-container { max-width:1280px !important; padding:2rem 2.2rem 3rem !important; }
.stApp h1,.stApp h2,.stApp h3,.stApp p,.stApp label,.stApp button,.stApp input,.stApp li,.stApp [data-baseweb="select"],.stApp [data-testid="stMarkdownContainer"] { font-family:"Segoe UI",Arial,sans-serif !important; }
.stApp h1,.stApp h2 { font-weight:700 !important; letter-spacing:-.04em; color:var(--navy); }
.stApp h2 { font-size:2.1rem !important; } .stApp h3 { font-size:1.35rem !important; font-weight:650 !important; color:var(--navy); }
.stApp p,.stApp label { font-size:1rem; line-height:1.55; }
.stApp [data-testid="stCaptionContainer"] p { color:var(--muted) !important; font-size:.88rem !important; }
.brand { display:flex; align-items:center; gap:13px; min-height:56px; }
.brand-symbol { width:48px;height:48px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(140deg,#0b7f84,#102d40);color:#f9d88f;box-shadow:0 6px 14px #0c596b20; }
.brand-name { font-size:1.45rem;font-weight:750;letter-spacing:-.04em;color:var(--navy); }
.brand-note { font-size:.8rem;color:var(--muted);margin-top:3px; }
.st-key-navigation { background:#e7edef;border-radius:15px;padding:5px !important; }
.stApp button { min-height:46px;border-radius:11px !important;transition:background .15s,box-shadow .15s,transform .15s; }
.stApp button p { font-size:.95rem !important;font-weight:650 !important; }
.stApp .stButton button { background:white;border:1px solid #c9d7df;color:var(--navy); }
.stApp .stButton button:hover { border-color:var(--teal);background:#eef8f6;box-shadow:0 5px 12px #0f4b5b12; }
.stApp button[kind="primary"] { background:linear-gradient(100deg,#087f84,#1165ac) !important;border:0 !important;color:white !important;box-shadow:0 5px 12px #076d8a22; }
.st-key-navigation button { background:transparent !important;border:0 !important;box-shadow:none !important; }
.st-key-navigation button[kind="primary"] { background:var(--navy) !important;color:white !important; }
.stApp button:focus-visible { outline:3px solid #cc952e !important;outline-offset:3px; }
.stApp hr { margin:1.1rem 0 1.6rem;border-color:#d8e2e7; }
.hero { position:relative;overflow:hidden;border-radius:26px;padding:36px 40px;min-height:220px;display:flex;align-items:center;gap:20px;background:radial-gradient(ellipse at 90% 20%,#175d68 0,transparent 60%),linear-gradient(125deg,#112c41,#081d2e);box-shadow:0 18px 40px #102d4018;margin-bottom:22px;color:white; }
.hero-copy { flex:1;position:relative;z-index:1; }
.hero-kicker { display:inline-block;color:#f1ce89;font-size:.72rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;margin-bottom:16px; }
.hero-title { font-size:clamp(2rem,3.5vw,3.3rem);font-weight:750;line-height:1.06;letter-spacing:-.05em;color:#fff;max-width:580px; }
.hero-description { color:#c4d7e1;font-size:1rem;line-height:1.65;max-width:440px;margin-top:16px; }
.hero-tags { display:flex;flex-wrap:wrap;gap:8px;margin-top:24px; }
.hero-tags span { border:1px solid #ffffff28;background:#ffffff09;border-radius:30px;padding:7px 12px;font-size:.78rem;color:#dae9ec; }
.hero-art { flex:0 0 260px;max-width:42%; }
.hero-art svg { width:100%;height:auto;display:block; }
.hero-tall { min-height:570px;display:block;padding:38px; }
.hero-tall .hero-art { max-width:100%;width:280px;margin:15px auto 0; }
.hero-tall .hero-title { font-size:3.1rem; }
.hero-compact { min-height:150px;padding:25px 32px;margin-bottom:14px; }
.hero-compact .hero-title { font-size:2.1rem; }
.hero-compact .hero-description { margin-top:9px; }
.hero-compact .hero-art { flex-basis:130px; }
.hero-compact .hero-kicker { margin-bottom:9px; }
.st-key-settings_card,.st-key-question_card,.st-key-result_card,.st-key-learn_card,[class*="st-key-award_card_"],[class*="st-key-country_card_"] { background:white;border:1px solid #d9e4e8 !important;border-radius:22px !important;padding:26px !important;box-shadow:0 10px 30px #16384a08; }
.st-key-settings_card { border-top:4px solid #0a8386 !important; }
.stApp [data-baseweb="select"] > div { background:#f3f7f9;border:1px solid #d6e2e8;border-radius:10px;min-height:45px; }
.st-key-question_card { border-top:4px solid #e4b65c !important; }
.st-key-question_card h3 { font-size:1.75rem !important;line-height:1.3; }
.st-key-question_card .stButton button { min-height:68px;background:#f6f9fb;text-align:left; }
.st-key-question_card .stButton button:disabled { opacity:1;color:#526777; }
[class*="st-key-correct_answer_"] button:disabled { background:#e5f5ed !important;border-color:#29825c !important;color:#14623c !important; }
[class*="st-key-wrong_answer_"] button:disabled { background:#fff0ef !important;border-color:#bc574d !important;color:#97382e !important; }
.score-strip { display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:8px 0 12px; }
.score-item { background:var(--navy);color:white;border-radius:16px;padding:18px 22px;border:1px solid #234557; }
.score-item:nth-child(2) { background:#f8edcf;border-color:#e7cf9a; }
.score-item:nth-child(3) { background:#e1f1ee;border-color:#badbd4; }
.score-label { font-size:.77rem;color:#c0d3de;text-transform:uppercase;letter-spacing:.07em; }
.score-value { font-size:1.9rem;font-weight:750;color:white;font-variant-numeric:tabular-nums; }
.score-item:nth-child(n+2) .score-label { color:#52665f; }
.score-item:nth-child(n+2) .score-value { color:#133c40; }
.round-label,.eyebrow { font-size:.73rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#587281; }
.round-summary { font-size:1.12rem;font-weight:650;margin-top:5px; }
.country-top { display:flex;justify-content:space-between;align-items:center;margin-bottom:18px; }
.country-code { display:grid;place-items:center;width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,#e7f4f0,#dce9f5);font-size:.82rem;font-weight:750;color:#0f6470; }
.country-region { font-size:.72rem;font-weight:650;text-transform:uppercase;letter-spacing:.06em;color:#607487; }
.fact-label { font-size:.75rem;text-transform:uppercase;letter-spacing:.07em;color:#61798b;margin-top:14px; }
.fact-value { font-size:1.16rem;font-weight:650;color:#15394b;line-height:1.45;margin:4px 0 15px; }
.fact-grid { display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:12px 0; }
.fact-tile { border:1px solid #dae6eb;border-radius:14px;background:#f5f9fa;padding:5px 18px; }
.award-medal { width:76px;height:76px;border:1px solid #dcba76;border-radius:50%;display:grid;place-items:center;background:radial-gradient(circle,#fff7d9,#ecd29a);font-size:2rem;color:#705222;margin-bottom:18px;box-shadow:0 0 0 7px #f8f2e4; }
.award-medal.locked { filter:grayscale(1);opacity:.65; }
.award-state { display:inline-block;border-radius:30px;padding:5px 12px;background:#edf1f5;color:#526575;font-size:.78rem; }
.award-state.earned { background:#def2e9;color:#186549; }
.result-number { font-size:4rem;letter-spacing:-.06em;font-weight:750;color:#0d7580; }
.result-unit { font-size:1rem;font-weight:400;letter-spacing:0;color:#526b7a; }
@media(max-width:850px) { .hero-tall { min-height:500px;padding:28px; }.hero-tall .hero-title { font-size:2.5rem; }.hero-tall .hero-art { width:220px; } }
@media(max-width:600px) {
 .stApp .block-container { padding:1rem 1rem 2rem !important; }
 .brand-name { font-size:1.25rem; }.brand-note { font-size:.72rem; }
 .st-key-navigation [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important;gap:3px !important; }
 .st-key-navigation [data-testid="stColumn"] { min-width:0 !important;width:25% !important;flex:1 !important; }
 .st-key-navigation button p { font-size:.8rem !important; }
 .hero { padding:25px;min-height:180px;border-radius:20px; }
 .hero-title { font-size:2.1rem; }.hero-art { flex-basis:105px; }.hero-description { font-size:.9rem; }
 .hero-tall { min-height:0;display:flex; }.hero-tall .hero-art { width:130px;max-width:30%;margin:0; }.hero-tall .hero-title { font-size:2.2rem; }
 .hero-tags { gap:5px;margin-top:15px; }.hero-tags span { font-size:.7rem;padding:5px 8px; }
 .hero-compact .hero-art { display:none; }.hero-compact .hero-title { font-size:1.8rem; }
 .st-key-settings_card,.st-key-question_card,.st-key-result_card,.st-key-learn_card,[class*="st-key-country_card_"],[class*="st-key-award_card_"] { padding:20px !important; }
 .score-strip { gap:7px; }.score-item { padding:12px; }.score-label { font-size:.62rem; }.score-value { font-size:1.4rem; }
 .fact-grid { grid-template-columns:1fr;gap:10px; }
}
@media(prefers-reduced-motion:reduce) { * { transition:none !important; } }

[data-testid="stDialog"] [role="dialog"] { position:fixed !important;left:0 !important;right:auto !important;top:0 !important;margin:0 !important;height:100dvh !important;max-height:100dvh !important;width:420px !important;max-width:94vw !important;border-radius:0 24px 24px 0 !important;overflow-y:auto !important; }
[data-testid="stDialog"] h2,[data-testid="stDialog"] h3,[data-testid="stDialog"] p,[data-testid="stDialog"] label,[data-testid="stDialog"] input { font-family:"Segoe UI",Arial,sans-serif !important; }
[class*="st-key-country_card_"] { padding:18px !important;border-radius:18px !important; }
[class*="st-key-country_card_"] h3 { font-size:1.15rem !important;margin:0 !important;padding:0 !important; }
[class*="st-key-country_card_"] .country-top { margin-bottom:4px; }
[class*="st-key-country_card_"] .country-code { width:36px;height:36px;font-size:.7rem; }
.compact-capital { color:#536b7a;font-size:.88rem;min-height:42px;line-height:1.45; }
.profile-note { font-size:.8rem;color:#536b7a;margin-top:8px; }
.browse-scope { display:inline-block;background:#dff0eb;color:#145c60;font-size:.85rem;font-weight:650;border-radius:30px;padding:7px 14px; }
.st-key-settings_menu button { font-size:1.4rem !important; }

</style>
""", unsafe_allow_html=True)


# Interface language is a display layer: canonical quiz answers and state never change.
UI_TRANSLATIONS = {'Explore': ['Entdecken', 'Explorar', '探索'], 'Learn': ['Lernen', 'Aprender', '学习'], 'Quiz': ['Quiz', 'Cuestionario', '测验'], 'Badges': ['Erfolge', 'Logros', '成就'], 'Settings': ['Einstellungen', 'Ajustes', '设置'], 'Profile': ['Profil', 'Perfil', '个人资料'], 'Display name': ['Anzeigename', 'Nombre visible', '显示名称'], 'App language': ['App-Sprache', 'Idioma de la aplicación', '应用语言'], 'Exploration area': ['Entdeckungsbereich', 'Área de exploración', '探索范围'], 'All countries': ['Alle Länder', 'Todos los países', '所有国家'], 'All Countries': ['Alle Länder', 'Todos los países', '所有国家'], 'One continent': ['Ein Kontinent', 'Un continente', '一个大洲'], 'One country': ['Ein Land', 'Un país', '一个国家'], 'Continent': ['Kontinent', 'Continente', '大洲'], 'Country': ['Land', 'País', '国家'], 'Apply settings': ['Einstellungen übernehmen', 'Aplicar ajustes', '应用设置'], 'World': ['Welt', 'Mundo', '世界'], 'Africa': ['Afrika', 'África', '非洲'], 'Asia': ['Asien', 'Asia', '亚洲'], 'Europe': ['Europa', 'Europa', '欧洲'], 'North America': ['Nordamerika', 'América del Norte', '北美洲'], 'South America': ['Südamerika', 'América del Sur', '南美洲'], 'Oceania': ['Ozeanien', 'Oceanía', '大洋洲'], 'Category': ['Kategorie', 'Categoría', '类别'], 'Difficulty': ['Schwierigkeit', 'Dificultad', '难度'], 'Questions': ['Fragen', 'Preguntas', '题数'], 'Timed challenge': ['Zeitlimit', 'Desafío con tiempo', '限时挑战'], 'Start quiz': ['Quiz starten', 'Iniciar cuestionario', '开始测验'], 'Build your challenge': ['Deine Herausforderung', 'Crea tu desafío', '创建挑战'], 'Your next adventure': ['Dein nächstes Abenteuer', 'Tu próxima aventura', '下一场冒险'], 'Mixed': ['Gemischt', 'Mixto', '混合'], 'Capitals': ['Hauptstädte', 'Capitales', '首都'], 'Heads of State': ['Staatsoberhäupter', 'Jefes de Estado', '国家元首'], 'Currency': ['Währung', 'Moneda', '货币'], 'Languages': ['Sprachen', 'Idiomas', '语言'], 'Country Identification': ['Land erkennen', 'Identificar países', '识别国家'], 'Geography / General Facts': ['Geografie / Fakten', 'Geografía / Datos', '地理与常识'], 'Continents': ['Kontinente', 'Continentes', '大洲'], 'True or False': ['Richtig oder falsch', 'Verdadero o falso', '判断题'], 'True': ['Richtig', 'Verdadero', '正确'], 'False': ['Falsch', 'Falso', '错误'], 'Easy': ['Leicht', 'Fácil', '简单'], 'Medium': ['Mittel', 'Medio', '中等'], 'Difficult': ['Schwer', 'Difícil', '困难'], 'Expert': ['Experte', 'Experto', '专家'], 'Return to current round': ['Zur laufenden Runde', 'Volver a la ronda actual', '返回当前轮次'], 'Scoring and hints': ['Punkte und Hinweise', 'Puntos y pistas', '计分与提示'], 'Current challenge': ['Aktuelle Herausforderung', 'Desafío actual', '当前挑战'], 'Change': ['Ändern', 'Cambiar', '更改'], 'Round score': ['Rundenpunkte', 'Puntos de la ronda', '本轮得分'], 'Current streak': ['Aktuelle Serie', 'Racha actual', '连续答对'], 'Hints remaining': ['Verbleibende Hinweise', 'Pistas restantes', '剩余提示'], 'Correct answer': ['Richtige Antwort', 'Respuesta correcta', '正确答案'], 'Your answer': ['Deine Antwort', 'Tu respuesta', '你的答案'], 'Removed by hint': ['Durch Hinweis entfernt', 'Eliminada por la pista', '由提示排除'], 'Use hint · −25 if correct': ['Hinweis nutzen · −25 bei richtiger Antwort', 'Usar pista · −25 si aciertas', '使用提示 · 答对扣25分'], 'Next question →': ['Nächste Frage →', 'Siguiente pregunta →', '下一题 →'], 'View results': ['Ergebnis ansehen', 'Ver resultados', '查看结果'], 'Your results': ['Dein Ergebnis', 'Tus resultados', '你的成绩'], 'Challenge complete': ['Herausforderung abgeschlossen', 'Desafío completado', '挑战完成'], 'Accuracy': ['Genauigkeit', 'Precisión', '正确率'], 'Correct answers': ['Richtige Antworten', 'Respuestas correctas', '答对题数'], 'Best streak': ['Beste Serie', 'Mejor racha', '最佳连对'], 'Play again': ['Erneut spielen', 'Jugar de nuevo', '再玩一次'], 'Change settings': ['Einstellungen ändern', 'Cambiar ajustes', '更改设置'], 'Try another continent': ['Anderen Kontinent wählen', 'Probar otro continente', '尝试其他大洲'], 'Try another country': ['Anderes Land wählen', 'Probar otro país', '尝试其他国家'], 'Review answers': ['Antworten prüfen', 'Revisar respuestas', '查看答题记录'], 'Answer review': ['Antwortübersicht', 'Revisión de respuestas', '答题回顾'], 'Choose a country': ['Land auswählen', 'Elegir un país', '选择国家'], 'Discover country →': ['Land entdecken →', 'Descubrir país →', '了解国家 →'], 'Search countries or capitals': ['Länder oder Hauptstädte suchen', 'Buscar países o capitales', '搜索国家或首都'], 'Previous': ['Zurück', 'Anterior', '上一页'], 'Next': ['Weiter', 'Siguiente', '下一页'], 'No countries match your search.': ['Keine Länder gefunden.', 'No hay países que coincidan.', '没有找到匹配的国家。'], 'Browse your world': ['Entdecke deine Welt', 'Explora tu mundo', '探索你的世界'], 'A little discovery, every day.': ['Jeden Tag etwas Neues entdecken.', 'Un pequeño descubrimiento cada día.', '每天发现一点新知。'], 'Choose your area in ☰ Settings, then search or open a country.': ['Wähle deinen Bereich unter ☰ Einstellungen. Suche dann nach einem Land.', 'Elige tu área en ☰ Ajustes y busca o abre un país.', '在☰设置中选择范围，然后搜索或打开一个国家。'], 'The world geography challenge': ['Die Welt-Geografie-Challenge', 'El desafío de geografía mundial', '世界地理挑战'], 'How well do you know your world?': ['Wie gut kennst du deine Welt?', '¿Cuánto conoces tu mundo?', '你有多了解世界？'], 'Go beyond the familiar. Challenge yourself on capitals, currencies, languages and the places in between.': ['Entdecke Neues. Teste dein Wissen über Hauptstädte, Währungen, Sprachen und Orte.', 'Descubre más. Ponte a prueba con capitales, monedas, idiomas y lugares.', '超越熟悉的事物，挑战首都、货币、语言与各地知识。'], 'World Quiz': ['Welt-Quiz', 'Cuestionario mundial', '世界测验'], 'Every answer takes you further.': ['Jede Antwort bringt dich weiter.', 'Cada respuesta te lleva más lejos.', '每个答案都让你更进一步。'], 'Think carefully. Build a streak. Discover something new.': ['Überlege gut. Baue eine Serie auf. Entdecke Neues.', 'Piensa bien. Crea una racha. Descubre algo nuevo.', '仔细思考，连续答对，发现新知。'], 'The country collection': ['Die Ländersammlung', 'La colección de países', '国家知识库'], 'Get to know the world.': ['Lerne die Welt kennen.', 'Conoce el mundo.', '认识世界。'], 'Build your knowledge, one country at a time. The details make all the difference.': ['Erweitere dein Wissen, Land für Land. Die Details machen den Unterschied.', 'Aprende país por país. Los detalles marcan la diferencia.', '逐国积累知识，细节让世界更精彩。'], 'Continent / region': ['Kontinent / Region', 'Continente / región', '大洲与地区'], 'Capital roles': ['Hauptstädte und Funktionen', 'Capitales y funciones', '首都及其职能'], 'Currencies': ['Währungen', 'Monedas', '货币'], 'Official languages in this collection': ['Erfasste Amtssprachen', 'Idiomas oficiales incluidos', '本知识库收录的官方语言'], 'Not included yet': ['Noch nicht enthalten', 'Aún no incluido', '暂未收录'], 'Country data source': ['Quelle der Länderdaten', 'Fuente de datos del país', '国家数据来源'], 'Capital-role source': ['Quelle zu Hauptstadtfunktionen', 'Fuente de las funciones de capital', '首都职能来源'], 'Political source': ['Politische Quelle', 'Fuente política', '政治资料来源'], 'Your explorer passport': ['Dein Entdeckerpass', 'Tu pasaporte de explorador', '探索者护照'], 'Curiosity deserves recognition.': ['Neugier verdient Anerkennung.', 'La curiosidad merece reconocimiento.', '好奇心值得嘉奖。'], 'Every right answer is a step forward. Collect milestones as your knowledge grows.': ['Jede richtige Antwort bringt dich weiter. Sammle Erfolge mit wachsendem Wissen.', 'Cada acierto es un paso adelante. Colecciona logros mientras aprendes.', '每次答对都是进步，在学习中收集成就。'], 'First Steps': ['Erste Schritte', 'Primeros pasos', '初次进步'], 'Century': ['Hundert Punkte', 'Cien puntos', '百分成就'], 'Round Finisher': ['Runde abgeschlossen', 'Ronda completada', '完成一轮'], 'Earned': ['Erreicht', 'Conseguido', '已获得'], 'In progress': ['In Arbeit', 'En progreso', '进行中'], 'Answer your first question correctly.': ['Beantworte deine erste Frage richtig.', 'Responde bien tu primera pregunta.', '第一次正确回答问题。'], 'Earn 100 points.': ['Sammle 100 Punkte.', 'Consigue 100 puntos.', '获得100分。'], 'Complete your first quiz round.': ['Schließe deine erste Quizrunde ab.', 'Completa tu primera ronda.', '完成第一轮测验。'], 'For curious minds. Across every border.': ['Für neugierige Köpfe. Über Grenzen hinweg.', 'Para mentes curiosas. Sin fronteras.', '为好奇的心，跨越每道边界。'], 'A WORLD TO DISCOVER': ['EINE WELT ZUM ENTDECKEN', 'UN MUNDO POR DESCUBRIR', '发现世界'], 'Data sources and coverage': ['Quellen und Datenumfang', 'Fuentes y cobertura', '数据来源与覆盖范围'], 'Preferences and profile last for this browser session. This is not a sign-in account.': ['Profil und Einstellungen gelten für diese Sitzung. Dies ist kein Benutzerkonto.', 'El perfil y los ajustes duran esta sesión. No es una cuenta de acceso.', '资料与偏好仅在本次浏览器会话有效，这不是登录账户。'], 'Country names and factual names retain the dataset spelling.': ['Länder- und Eigennamen behalten die Schreibweise der Datenquelle.', 'Los nombres de países y datos conservan la escritura original.', '国家及事实名称保留数据来源的拼写。'], 'Area changes update Explore and Learn and the next quiz setup. Your current round is kept.': ['Der Bereich gilt für Entdecken, Lernen und das nächste Quiz. Die laufende Runde bleibt erhalten.', 'El área cambia Explorar, Aprender y el próximo cuestionario. La ronda actual se conserva.', '范围设置应用于探索、学习及下一轮测验，当前轮次保留。'], 'Capital / capital roles': ['Hauptstädte und Funktionen', 'Capitales y funciones', '首都及其职能'], 'capital': ['Hauptstadt', 'capital', '首都'], 'constitutional capital': ['Verfassungshauptstadt', 'capital constitucional', '宪法规定首都'], 'seat of government': ['Regierungssitz', 'sede del gobierno', '政府所在地'], 'administrative capital': ['Verwaltungshauptstadt', 'capital administrativa', '行政首都'], 'royal and legislative capital': ['Königs- und Parlamentssitz', 'capital real y legislativa', '王室与立法首都'], 'commercial capital': ['Wirtschaftshauptstadt', 'capital comercial', '商业首都'], 'President': ['Präsident', 'Presidente', '总统'], 'Federal President': ['Bundespräsident', 'Presidente federal', '联邦总统'], 'King': ['König', 'Rey', '国王']}
UI_TEMPLATES = [('{n} countries', ['{n} Länder', '{n} países', '{n}个国家']), ('6 continents', ['6 Kontinente', '6 continentes', '6个大洲']), ('10 quiz categories', ['10 Quizkategorien', '10 categorías', '10类测验']), ('Page {page} of {pages} · {count} countries', ['Seite {page} von {pages} · {count} Länder', 'Página {page} de {pages} · {count} países', '第{page}/{pages}页 · {count}个国家']), ('Question {n} of {total} · {kind} · {difficulty}', ['Frage {n} von {total} · {kind} · {difficulty}', 'Pregunta {n} de {total} · {kind} · {difficulty}', '第{n}/{total}题 · {kind} · {difficulty}']), ('Time remaining: {n} seconds', ['Verbleibende Zeit: {n} Sekunden', 'Tiempo restante: {n} segundos', '剩余时间：{n}秒']), ('Which place serves as the {role} of {name}?', ['Welcher Ort ist {role} von {name}?', '¿Qué lugar es {role} de {name}?', '{name}的{role}是哪里？']), ('{place} is the {role} of which country?', ['{place} ist {role} welchen Landes?', '¿De qué país es {place} la {role}?', '{place}是哪个国家的{role}？']), ('{place} is the {role} of {name}.', ['{place} ist {role} von {name}.', '{place} es {role} de {name}.', '{place}是{name}的{role}。']), ('Which of these currencies is used in {name}?', ['Welche dieser Währungen wird in {name} verwendet?', '¿Cuál de estas monedas se usa en {name}?', '{name}使用以下哪种货币？']), ('{name} uses {currencies}.', ['{name} verwendet {currencies}.', '{name} utiliza {currencies}.', '{name}使用{currencies}。']), ('Which of these is an official language of {name}?', ['Welche dieser Sprachen ist Amtssprache in {name}?', '¿Cuál es un idioma oficial de {name}?', '以下哪种是{name}的官方语言？']), ('{language} is an official language of {name}.', ['{language} ist Amtssprache in {name}.', '{language} es un idioma oficial de {name}.', '{language}是{name}的官方语言。']), ('In which geographic subregion is {name}?', ['In welcher geografischen Teilregion liegt {name}?', '¿En qué subregión geográfica está {name}?', '{name}位于哪个地理分区？']), ('{name} is in {region}, within {continent}.', ['{name} liegt in {region}, in {continent}.', '{name} está en {region}, en {continent}.', '{name}位于{continent}的{region}。']), ('Which of these countries shares a land border with {name}?', ['Welches dieser Länder hat eine Landgrenze mit {name}?', '¿Qué país comparte una frontera terrestre con {name}?', '以下哪个国家与{name}有陆地边界？']), ('{other} and {name} share a land border.', ['{other} und {name} haben eine gemeinsame Landgrenze.', '{other} y {name} comparten una frontera terrestre.', '{other}与{name}有陆地边界。']), ('On which continent is {name}?', ['Auf welchem Kontinent liegt {name}?', '¿En qué continente está {name}?', '{name}位于哪个大洲？']), ('{name} is in {continent}.', ['{name} liegt in {continent}.', '{name} está en {continent}.', '{name}位于{continent}。']), ('These clues describe {name}.', ['Diese Hinweise beschreiben {name}.', 'Estas pistas describen {name}.', '这些线索描述的是{name}。']), ('Who is the {title} and head of state of {name}? (Record verified {verified})', ['Wer ist {title} und Staatsoberhaupt von {name}? (Geprüft am {verified})', '¿Quién es {title} y jefe de Estado de {name}? (Verificado: {verified})', '谁是{name}的{title}及国家元首？（资料核验：{verified}）']), ('{n} unique questions will be included · {capacity} available for these filters.', ['{n} verschiedene Fragen · {capacity} für diese Auswahl verfügbar.', '{n} preguntas únicas · {capacity} disponibles para estos filtros.', '本轮包含{n}道不同题目 · 此范围可用{capacity}道题。']), ('This round will contain {n} questions, without repeating the same question.', ['Diese Runde enthält {n} Fragen ohne Wiederholung.', 'Esta ronda contiene {n} preguntas sin repetición.', '本轮有{n}道题，不重复题目。']), ('{n} countries · Progress lasts for this browser session.', ['{n} Länder · Fortschritt gilt für diese Sitzung.', '{n} países · Progreso durante esta sesión.', '{n}个国家 · 进度仅在本次浏览器会话有效。'])]
UI_TRANSLATIONS.update({'Correct!': ['Richtig!', '¡Correcto!', '答对了！'], 'Time is up.': ['Die Zeit ist abgelaufen.', 'Se acabó el tiempo.', '时间到。'], 'Answer recorded': ['Antwort erfasst', 'Respuesta registrada', '答案已记录'], 'Correct': ['Richtig', 'Correcto', '正确'], 'Incorrect': ['Falsch', 'Incorrecto', '错误'], 'Timed out': ['Zeit abgelaufen', 'Tiempo agotado', '超时'], 'Unanswered': ['Nicht beantwortet', 'Sin respuesta', '未作答'], 'points': ['Punkte', 'puntos', '分'], 'Only recently verified political records are included. Coverage is currently limited.': ['Es werden nur kürzlich geprüfte politische Angaben verwendet. Der Umfang ist begrenzt.', 'Solo se incluyen datos políticos verificados recientemente. La cobertura es limitada.', '仅收录近期核验的政治资料，覆盖范围有限。'], 'Your chosen country stays selected; difficulty changes question formats and answer choices.': ['Dein Land bleibt ausgewählt. Die Schwierigkeit ändert Frageformen und Antwortmöglichkeiten.', 'Tu país sigue seleccionado; la dificultad cambia los formatos y las opciones.', '所选国家保持不变，难度会改变题型及选项。'], 'No verified questions match these filters. Choose Mixed, another country, or a lower difficulty.': ['Keine geprüften Fragen für diese Auswahl. Wähle Gemischt, ein anderes Land oder eine niedrigere Schwierigkeit.', 'No hay preguntas verificadas para estos filtros. Elige Mixto, otro país o menor dificultad.', '此筛选范围没有可核验题目，请选择混合、其他国家或更低难度。'], 'Correct answers earn 100 base points, multiplied by difficulty: Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2.': ['Richtige Antworten bringen 100 Basispunkte: Leicht ×1, Mittel ×1,25, Schwer ×1,5, Experte ×2.', 'Cada acierto da 100 puntos base: Fácil ×1, Medio ×1,25, Difícil ×1,5, Experto ×2.', '答对获100基础分，简单×1、中等×1.25、困难×1.5、专家×2。'], "Fast answers earn 25 extra points. Every third correct answer in a streak adds 50; every fifth adds 100. A hint removes one wrong option and deducts 25 from a correct answer's award. Each round has three hints.": ['Schnelle Antworten bringen 25 Bonuspunkte. Jede dritte richtige Antwort in Folge bringt 50, jede fünfte 100. Ein Hinweis entfernt eine falsche Option und zieht bei richtiger Antwort 25 Punkte ab. Drei Hinweise pro Runde.', 'Responder rápido añade 25 puntos. Cada tercer acierto seguido añade 50; cada quinto, 100. Una pista elimina una opción incorrecta y resta 25 puntos si aciertas. Tres pistas por ronda.', '快速答对加25分。每连续答对3题加50分，每5题加100分。提示排除一个错误选项，答对扣25分，每轮有3次提示。'], 'A perfect round without hints adds 250 points × difficulty. Wrong and timed-out answers earn zero. You can always use Next to read the explanation at your own pace.': ['Eine perfekte Runde ohne Hinweise bringt 250 Punkte × Schwierigkeit. Falsche Antworten und Zeitüberschreitungen bringen null. Mit Weiter liest du Erklärungen in deinem Tempo.', 'Una ronda perfecta sin pistas añade 250 puntos × dificultad. Los errores y el tiempo agotado dan cero. Avanza cuando termines de leer la explicación.', '全对且未用提示可获250×难度的奖励分。答错或超时得0分。阅读解析后可自行进入下一题。']})
UI_TEMPLATES.extend([('{points} lifetime session points · {rounds} rounds completed', ['{points} Sitzungspunkte · {rounds} Runden abgeschlossen', '{points} puntos en esta sesión · {rounds} rondas completadas', '本次会话共{points}分 · 已完成{rounds}轮']), ('Perfect round without hints: +{points} bonus points.', ['Perfekte Runde ohne Hinweise: +{points} Bonuspunkte.', 'Ronda perfecta sin pistas: +{points} puntos extra.', '全对且未用提示：奖励{points}分。']), ('Neighbours in this collection: {names}', ['Erfasste Nachbarländer: {names}', 'Países vecinos incluidos: {names}', '本知识库收录的邻国：{names}']), ('Political record verified {date}.', ['Politische Angaben geprüft am {date}.', 'Dato político verificado: {date}.', '政治资料核验日期：{date}。']), ('+{points} points · Base {base} · Speed +{speed} · Streak +{streak} · Hint −{hint}', ['+{points} Punkte · Basis {base} · Tempo +{speed} · Serie +{streak} · Hinweis −{hint}', '+{points} puntos · Base {base} · Rapidez +{speed} · Racha +{streak} · Pista −{hint}', '+{points}分 · 基础{base} · 速度+{speed} · 连对+{streak} · 提示−{hint}']), ('Incorrect / unanswered: {wrong} · Timed out: {timeout} · Average response time: {seconds} seconds', ['Falsch / unbeantwortet: {wrong} · Zeitüberschreitung: {timeout} · Durchschnitt: {seconds} Sekunden', 'Incorrectas / sin responder: {wrong} · Tiempo agotado: {timeout} · Promedio: {seconds} segundos', '答错或未作答：{wrong} · 超时：{timeout} · 平均答题时间：{seconds}秒']), ('{answer} is recorded as {title} of {name}, verified {date}. Head of state and head of government can be different offices.', ['{answer} ist als {title} von {name} erfasst, geprüft am {date}. Staatsoberhaupt und Regierungschef können unterschiedliche Ämter sein.', '{answer} figura como {title} de {name}, verificado el {date}. La jefatura del Estado y del Gobierno pueden ser cargos distintos.', '资料记载{answer}为{name}的{title}，核验日期{date}。国家元首与政府首脑可能是不同职务。'])])
APP_LANGUAGES = ["English", "Deutsch", "Español", "中文（普通话）"]

UI_TRANSLATIONS.update({"Landmarks": ["Sehenswürdigkeiten", "Lugares de interés", "地标"]})
UI_TRANSLATIONS.update({"Smaller question pools produce shorter rounds to avoid repeating the same facts.": [
    "Kleine Fragenpools ergeben kürzere Runden, damit dieselben Fakten nicht wiederholt werden.",
    "Los grupos pequeños de preguntas producen rondas más cortas para evitar repetir los mismos datos.",
    "题库较小时，本轮题数会减少，以免重复考查相同知识。"]})
UI_TEMPLATES.append(("Up to {n} questions · no repeated facts in the same round.", [
    "Bis zu {n} Fragen · keine wiederholten Fakten in derselben Runde.",
    "Hasta {n} preguntas · sin repetir datos en la misma ronda.", "最多{n}道题 · 同一轮不重复考查相同知识。"]))
UI_TEMPLATES.extend([('In which country is the UNESCO World Heritage site {site}?',
  ['In welchem Land liegt die UNESCO-Welterbestätte {site}?',
   '¿En qué país está el sitio del Patrimonio Mundial de la UNESCO {site}?',
   '联合国教科文组织世界遗产{site}位于哪个国家？']),
 ('Which of these UNESCO World Heritage sites is in {name}?',
  ['Welche dieser UNESCO-Welterbestätten liegt in {name}?',
   '¿Cuál de estos sitios del Patrimonio Mundial de la UNESCO está en {name}?',
   '以下哪个联合国教科文组织世界遗产位于{name}？']),
 ('{site} is in {name}.', ['{site} liegt in {name}.', '{site} está en {name}.', '{site}位于{name}。']),
 ('Which country has the larger total area: {name} or {other}?',
  ['Welches Land hat die größere Gesamtfläche: {name} oder {other}?',
   '¿Qué país tiene mayor superficie total: {name} o {other}?',
   '哪个国家的总面积更大：{name}还是{other}？']),
 ('Which country-code internet domain belongs to {name}?',
  ['Welche länderspezifische Internetdomain gehört zu {name}?',
   '¿Qué dominio de internet de país pertenece a {name}?',
   '{name}的国家互联网域名是哪个？']),
 ('Which international telephone calling code belongs to {name}?',
  ['Welche internationale Telefonvorwahl gehört zu {name}?',
   '¿Qué prefijo telefónico internacional pertenece a {name}?',
   '{name}的国际电话区号是哪个？']),
 ('{name} is landlocked.', ['{name} ist ein Binnenstaat.', '{name} no tiene salida al mar.', '{name}是内陆国家。']),
 ('{name} has a coastline.', ['{name} hat eine Küste.', '{name} tiene costa.', '{name}拥有海岸线。']),
 ('Which country shares land borders with both {first} and {second}?',
  ['Welches Land grenzt sowohl an {first} als auch an {second}?',
   '¿Qué país tiene fronteras terrestres con {first} y {second}?',
   '哪个国家同时与{first}和{second}有陆地边界？']),
 ('{name} shares land borders with {first} and {second}.',
  ['{name} grenzt an {first} und {second}.',
   '{name} tiene fronteras terrestres con {first} y {second}.',
   '{name}与{first}和{second}有陆地边界。'])])


def tr(value):
    if not isinstance(value, str):
        return value
    language = st.session_state.get("app_language", "English")
    if language not in APP_LANGUAGES or language == "English":
        return value
    idx = APP_LANGUAGES.index(language) - 1
    if value in UI_TRANSLATIONS:
        return UI_TRANSLATIONS[value][idx]
    import re
    for source, variants in UI_TEMPLATES:
        keys = re.findall(r"\{(\w+)\}", source)
        parts = re.split(r"\{\w+\}", source)
        pattern = "(.*?)".join(re.escape(part) for part in parts)
        match = re.fullmatch(pattern, value)
        if match:
            fields = dict(zip(keys, match.groups()))
            fields = {key: UI_TRANSLATIONS[v][idx] if v in UI_TRANSLATIONS else v for key, v in fields.items()}
            return variants[idx].format(**fields)
    return value


def option_formatter(values):
    # Freeze display labels for this render; canonical values remain unchanged.
    labels = {v: tr(v) for v in values}
    return lambda value: labels.get(value, str(value))


def localize_html(content):
    import re
    def convert(match):
        raw = match.group(1)
        text = unescape(raw)
        stripped = text.strip()
        if not stripped:
            return match.group(0)
        return ">" + escape(text.replace(stripped, tr(stripped))) + "<"
    return re.sub(r">([^<>]+)<", convert, content)


def localized_question(q):
    # Identification has variable clues, so translate its structure directly.
    if q["id"].endswith(":identify"):
        c = get_country(q["country_id"])
        lang = st.session_state.get("app_language", "English")
        if lang == "English":
            return q["prompt"]
        role, capital = tr(c["capitals"][0]["role"]), c["capitals"][0]["name"]
        currencies = [f"{x['name']} ({x['code']})" for x in c["currencies"]]
        included = next((v for v in currencies if v in q["prompt"]), None)
        language = next((v for v in c["official_languages"] if v in q["prompt"]), None)
        if lang == "Deutsch":
            text = f"Welches Land ist gesucht? {role}: {capital}."
            if included: text += f" Währung: {included}."
            if language: text += f" Eine Amtssprache: {language}."
        elif lang == "Español":
            text = f"Identifica el país. {role}: {capital}."
            if included: text += f" Moneda: {included}."
            if language: text += f" Un idioma oficial: {language}."
        else:
            text = f"识别国家：{role}为{capital}。"
            if included: text += f"货币：{included}。"
            if language: text += f"一种官方语言：{language}。"
        return text
    return tr(q["prompt"])


def apply_preferences():
    pending = st.session_state.pop("pending_preferences", None)
    if pending:
        st.session_state.update(pending)
        area, cid = st.session_state.scope_continent, st.session_state.scope_country
        st.session_state.filter_continent = area
        st.session_state.filter_country = cid
        st.session_state.explore_page = 0
        st.session_state.explore_search = ""
        st.session_state.show_setup = True
        ids = [c["id"] for c in scoped_countries()]
        if st.session_state.get("learn_country") not in ids:
            st.session_state.learn_country = ids[0] if ids else "NGA"


def scoped_countries():
    mode = st.session_state.get("scope_mode", "All countries")
    if mode == "One country":
        country = get_country(st.session_state.get("scope_country", "NGA"))
        return [country] if country else []
    if mode == "One continent":
        return get_countries(st.session_state.get("scope_continent", "Africa"))
    return get_countries("World")


def scope_label():
    mode = st.session_state.get("scope_mode", "All countries")
    if mode == "One country":
        c = get_country(st.session_state.scope_country)
        return c["name"] if c else tr("All countries")
    return tr(st.session_state.scope_continent) if mode == "One continent" else tr("All countries")



# ACCOUNT SETUP (server-side only; never put credentials in this Python file).
# Install authentication support: python -m pip install "streamlit[auth]"
# .streamlit/secrets.toml:
# [auth]
# redirect_uri = "http://localhost:8502/oauth2callback"
# cookie_secret = "GENERATE_A_LONG_RANDOM_SECRET"
# [auth.google]
# client_id = "GOOGLE_CLIENT_ID"
# client_secret = "GOOGLE_CLIENT_SECRET"
# server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
# [auth.account] # optional email/password provider (Auth0 database connection)
# client_id = "AUTH0_CLIENT_ID"
# client_secret = "AUTH0_CLIENT_SECRET"
# server_metadata_url = "https://YOUR_AUTH0_DOMAIN/.well-known/openid-configuration"
# [profiles]
# url = "https://YOUR_PROJECT.supabase.co"
# server_key = "SUPABASE_SERVER_SECRET_KEY"
# Supabase SQL Editor (private table accessed only by this authenticated server):
# create table public.world_explorer_profiles (
#   user_id text primary key, profile jsonb not null default '{}'::jsonb,
#   updated_at timestamptz not null default now());
# alter table public.world_explorer_profiles enable row level security;
# revoke all on public.world_explorer_profiles from anon, authenticated;
# grant select, insert, update on public.world_explorer_profiles to service_role;
# No public policies: the server derives user_id from verified OIDC identity.
# Google and email accounts are separate identities unless linked at the provider.

UI_TRANSLATIONS.update({
 "Profile photo": ["Profilfoto", "Foto de perfil", "头像"],
 "Remove photo": ["Foto entfernen", "Eliminar foto", "删除头像"],
 "Signed in": ["Angemeldet", "Sesión iniciada", "已登录"],
 "Sign out": ["Abmelden", "Cerrar sesión", "退出登录"],
 "Continue with Google": ["Mit Google fortfahren", "Continuar con Google", "使用Google登录"],
 "Email sign-in / Create account": ["Mit E-Mail anmelden / Konto erstellen", "Correo / Crear cuenta", "邮箱登录 / 创建账户"],
 "Guest explorer": ["Gast", "Explorador invitado", "访客"],
 "Saved to your account": ["In deinem Konto gespeichert", "Guardado en tu cuenta", "已保存至账户"],
 "Progress lasts for this browser session": ["Fortschritt gilt für diese Sitzung", "El progreso dura esta sesión", "进度仅在本次会话有效"],
 "Sign in to save your profile and progress across visits.": ["Melde dich an, um Profil und Fortschritt zu speichern.", "Inicia sesión para guardar tu perfil y progreso.", "登录以保存个人资料和进度。"],
 "Account sign-in is being set up. You can continue as a guest.": ["Die Anmeldung wird eingerichtet. Du kannst als Gast fortfahren.", "El acceso se está configurando. Puedes continuar como invitado.", "账户登录正在配置，可继续以访客身份使用。"],
 "Please choose a photo smaller than 2 MB.": ["Bitte wähle ein Foto unter 2 MB.", "Elige una foto de menos de 2 MB.", "请选择小于2 MB的照片。"],
 "This photo could not be opened. Please choose another image.": ["Das Foto konnte nicht geöffnet werden. Wähle ein anderes Bild.", "No se pudo abrir la foto. Elige otra imagen.", "无法打开照片，请选择其他图片。"],
 "Your saved profile could not be reached. Changes have not been saved online.": ["Dein Profil ist nicht erreichbar. Änderungen wurden nicht online gespeichert.", "No se pudo acceder a tu perfil. Los cambios no se guardaron en línea.", "无法访问已保存的资料，更改尚未在线保存。"],
 "Signed-in profiles save online when the account connection is ready. Guest profiles last for this session.": ["Angemeldete Profile werden bei eingerichteter Verbindung online gespeichert. Gastprofile gelten für diese Sitzung.", "Los perfiles se guardan en línea al conectar la cuenta. Los perfiles de invitados duran esta sesión.", "账户连接就绪后，登录资料会在线保存，访客资料仅在本次会话有效。"],
 "Email registration and password reset are available on the secure sign-in screen.": ["Registrierung und Passwortzurücksetzung findest du auf der sicheren Anmeldeseite.", "El registro y el restablecimiento de contraseña están en la pantalla segura de acceso.", "邮箱注册和密码重置可在安全登录页面完成。"],
 "Sign-in could not start. Please check the account connection.": ["Anmeldung konnte nicht gestartet werden. Prüfe die Kontoverbindung.", "No se pudo iniciar el acceso. Revisa la conexión de la cuenta.", "无法启动登录，请检查账户连接。"]
})

PROFILE_KEYS = ("profile_name", "profile_photo", "app_language", "scope_mode",
                "scope_continent", "scope_country", "points", "rounds_finished", "recent", "recent_facts")


def account_identity():
    try:
        if not st.user.is_logged_in:
            return None
        claims = dict(st.user)
        issuer, subject = claims.get("iss"), claims.get("sub")
        if not issuer or not subject:
            return None
        claims["profile_id"] = hashlib.sha256((str(issuer) + "\0" + str(subject)).encode()).hexdigest()
        return claims
    except (AttributeError, KeyError):
        return None


def secret_section(name):
    try:
        return dict(st.secrets.get(name, {}))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return {}


def provider_ready(name):
    auth = secret_section("auth")
    provider = auth.get(name, {})
    return bool(auth.get("redirect_uri") and auth.get("cookie_secret") and
                all(provider.get(k) for k in ("client_id", "client_secret", "server_metadata_url")))


def profile_connection():
    config = secret_section("profiles")
    url, key = config.get("url", ""), config.get("server_key", "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co"):
        return None
    return (url.rstrip("/"), key) if key else None


def profile_request(identity, payload=None):
    connection = profile_connection()
    if not connection:
        raise RuntimeError("Profile storage is not configured")
    url, key = connection
    headers = {"apikey": key, "Content-Type": "application/json"}
    # Legacy JWT service keys require Authorization; new sb_secret keys use apikey.
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    uid = identity["profile_id"]
    if payload is None:
        route = "/rest/v1/world_explorer_profiles?user_id=eq." + uid + "&select=profile"
        data, method = None, "GET"
    else:
        route = "/rest/v1/world_explorer_profiles?on_conflict=user_id"
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        data = json.dumps({"user_id": uid, "profile": payload}).encode()
        method = "POST"
    request = urllib.request.Request(url + route, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(2_000_000)
    return json.loads(raw) if raw else None


def restore_account_profile():
    identity = account_identity()
    if not identity:
        return
    uid = identity["profile_id"]
    if st.session_state.get("account_loaded") == uid:
        return
    if not st.session_state.get("account_loaded"):
        st.session_state.profile_name = str(identity.get("name", ""))[:40]
    if not profile_connection():
        return
    try:
        rows = profile_request(identity)
        values = rows[0]["profile"] if rows else {}
        for key in PROFILE_KEYS:
            if key not in values:
                continue
            value = values[key]
            if key in ("points", "rounds_finished") and isinstance(value, int) and value >= 0:
                st.session_state[key] = value
            elif key in ("recent", "recent_facts") and isinstance(value, list):
                st.session_state[key] = [x for x in value if isinstance(x, str)][-500:]
            elif key == "profile_name" and isinstance(value, str):
                st.session_state[key] = value[:40]
            elif key == "profile_photo" and isinstance(value, str) and value.startswith("data:image/jpeg;base64,") and len(value) < 500_000:
                st.session_state[key] = value
            elif key == "app_language" and value in APP_LANGUAGES:
                st.session_state[key] = value
            elif key == "scope_mode" and value in ("All countries", "One country", "One continent"):
                st.session_state[key] = value
            elif key == "scope_continent" and value in AREAS:
                st.session_state[key] = value
            elif key == "scope_country" and (value == "all" or get_country(value)):
                st.session_state[key] = value
        st.session_state.account_loaded = uid
        st.session_state.profile_save_error = False
        st.session_state.profile_saved_fingerprint = json.dumps({k:st.session_state.get(k) for k in PROFILE_KEYS}, sort_keys=True) if rows else ""
    except Exception:
        # Do not write until a successful read: an outage must not overwrite saved progress.
        st.session_state.profile_save_error = True


def save_account_profile():
    identity = account_identity()
    if not identity or st.session_state.get("account_loaded") != identity["profile_id"]:
        return
    payload = {k: st.session_state.get(k) for k in PROFILE_KEYS}
    fingerprint = json.dumps(payload, sort_keys=True)
    if fingerprint == st.session_state.get("profile_saved_fingerprint"):
        return
    try:
        profile_request(identity, payload)
        st.session_state.profile_saved_fingerprint = fingerprint
        st.session_state.profile_save_error = False
    except Exception:
        st.session_state.profile_save_error = True


def start_account_login(provider):
    save_account_profile()
    try:
        st.login(provider)
    except Exception:
        st.error(tr("Sign-in could not start. Please check the account connection."))


def account_photo_upload():
    uploaded = st.file_uploader(tr("Profile photo"), type=["jpg", "jpeg", "png", "webp"], key="profile_photo_upload")
    if uploaded is None:
        return
    raw = uploaded.getvalue()
    if len(raw) > 2_000_000:
        st.error(tr("Please choose a photo smaller than 2 MB."))
        return
    digest = hashlib.sha256(raw).hexdigest()
    if digest == st.session_state.get("photo_upload_digest"):
        return
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.width * original.height > 20_000_000:
                raise ValueError("Photo is too large")
            picture = ImageOps.fit(ImageOps.exif_transpose(original).convert("RGB"), (256, 256))
            output = io.BytesIO()
            picture.save(output, format="JPEG", quality=85)
        st.session_state.profile_photo = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()
        st.session_state.photo_upload_digest = digest
        save_account_profile()
        st.rerun()
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        st.error(tr("This photo could not be opened. Please choose another image."))


def account_profile_controls():
    identity = account_identity()
    if identity:
        st.caption(tr("Signed in") + " · " + str(identity.get("email", identity.get("name", ""))))
        if st.button(tr("Sign out"), key="profile_logout", use_container_width=True):
            save_account_profile()
            st.logout()
    else:
        st.caption(tr("Sign in to save your profile and progress across visits."))
        st.button(tr("Continue with Google"), key="profile_google", disabled=not provider_ready("google"),
                  use_container_width=True, on_click=start_account_login, args=("google",))
        st.button(tr("Email sign-in / Create account"), key="profile_email", disabled=not provider_ready("account"),
                  use_container_width=True, on_click=start_account_login, args=("account",))
        if not provider_ready("google") and not provider_ready("account"):
            st.caption(tr("Account sign-in is being set up. You can continue as a guest."))
        else:
            st.caption(tr("Email registration and password reset are available on the secure sign-in screen."))
    photo = st.session_state.get("profile_photo", "")
    if photo:
        html(f'<img class="profile-preview" src="{escape(photo, quote=True)}" alt="Profile photo">')
        if st.button(tr("Remove photo"), key="profile_remove_photo"):
            st.session_state.profile_photo = ""
            st.session_state.photo_upload_digest = None
            # Reset uploader too, so the deleted image cannot be applied again.
            st.session_state.pop("profile_photo_upload", None)
            save_account_profile()
            st.rerun()
    account_photo_upload()
    if st.session_state.get("profile_save_error"):
        st.warning(tr("Your saved profile could not be reached. Changes have not been saved online."))


def settings_body():
    st.subheader(tr("Profile"))
    account_profile_controls()
    name = st.text_input(tr("Display name"), value=st.session_state.get("profile_name", ""),
                         max_chars=40, key="preferences_name")
    language = st.selectbox(tr("App language"), APP_LANGUAGES,
                           index=APP_LANGUAGES.index(st.session_state.app_language), key="preferences_language")
    st.caption(tr("Country names and factual names retain the dataset spelling."))
    st.divider()
    modes = ["All countries", "One continent", "One country"]
    mode = st.selectbox(tr("Exploration area"), modes,
                        index=modes.index(st.session_state.scope_mode), format_func=option_formatter(modes), key="preferences_mode")
    area, cid = "World", "all"
    if mode == "One continent":
        previous = st.session_state.scope_continent
        area = st.selectbox(tr("Continent"), CONTINENTS,
                            index=CONTINENTS.index(previous) if previous in CONTINENTS else 0,
                            format_func=option_formatter(CONTINENTS), key="preferences_continent")
    elif mode == "One country":
        ids = [c["id"] for c in get_countries("World")]
        previous = st.session_state.scope_country
        cid = st.selectbox(tr("Country"), ids, index=ids.index(previous) if previous in ids else ids.index("NGA"),
                           format_func=lambda i: get_country(i)["name"], key="preferences_country")
        area = get_country(cid)["continent"]
    st.caption(tr("Area changes update Explore and Learn and the next quiz setup. Your current round is kept."))
    if st.button(tr("Apply settings"), key="apply_preferences", type="primary", use_container_width=True):
        st.session_state.settings_open = False
        st.session_state.pending_preferences = {"profile_name": name.strip(), "app_language": language,
            "scope_mode": mode, "scope_continent": area, "scope_country": cid}
        st.rerun()
    st.caption(tr("Signed-in profiles save online when the account connection is ready. Guest profiles last for this session."))
    render_data_sources()


def dismiss_settings():
    st.session_state.settings_open = False


def open_settings():
    st.dialog(tr("Settings"), width="small", on_dismiss=dismiss_settings)(settings_body)()



# Offline quiz facts, checked against country data and UNESCO DataHub on 2026-10-08.
COUNTRIES.extend([{'id': 'AFG', 'name': 'Afghanistan', 'continent': 'Asia', 'region': 'Southern Asia', 'capitals': [{'name': 'Kabul', 'role': 'capital'}], 'currencies': [{'code': 'AFN', 'name': 'Afghan afghani'}], 'languages': ['Dari', 'Pashto', 'Turkmen'], 'official_languages': ['Dari', 'Pashto'], 'borders': ['IRN', 'PAK', 'TKM', 'UZB', 'TJK', 'CHN'], 'landlocked': True, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-08'}, {'id': 'PAK', 'name': 'Pakistan', 'continent': 'Asia', 'region': 'Southern Asia', 'capitals': [{'name': 'Islamabad', 'role': 'capital'}], 'currencies': [{'code': 'PKR', 'name': 'Pakistani rupee'}], 'languages': ['English', 'Urdu'], 'official_languages': ['English', 'Urdu'], 'borders': ['AFG', 'CHN', 'IND', 'IRN'], 'landlocked': False, 'tier': 3, 'population': None, 'source': 'https://github.com/mledoze/countries', 'data_date': '2026-10-08'}])
COUNTRY_DETAILS = {'AFG': {'area_km2': 652230,
         'domains': ['.af'],
         'calling_codes': ['+93'],
         'landmarks': [{'name': 'Minaret and Archaeological Remains of Jam',
                        'source': 'https://whc.unesco.org/en/list/211/'},
                       {'name': 'Cultural Landscape and Archaeological Remains of the Bamiyan Valley',
                        'source': 'https://whc.unesco.org/en/list/208/'}]},
 'ALB': {'area_km2': 28748,
         'domains': ['.al'],
         'calling_codes': ['+355'],
         'landmarks': [{'name': 'Butrint', 'source': 'https://whc.unesco.org/en/list/570/'},
                       {'name': 'Historic Centres of Berat and Gjirokastra',
                        'source': 'https://whc.unesco.org/en/list/569/'}]},
 'AND': {'area_km2': 468,
         'domains': ['.ad'],
         'calling_codes': ['+376'],
         'landmarks': [{'name': 'Madriu-Perafita-Claror Valley',
                        'source': 'https://whc.unesco.org/en/list/1160/'}]},
 'ARG': {'area_km2': 2780400,
         'domains': ['.ar'],
         'calling_codes': ['+54'],
         'landmarks': [{'name': 'Los Glaciares National Park', 'source': 'https://whc.unesco.org/en/list/145/'},
                       {'name': 'Iguazu National Park', 'source': 'https://whc.unesco.org/en/list/303/'},
                       {'name': 'Cueva de las Manos, Río Pinturas',
                        'source': 'https://whc.unesco.org/en/list/936/'}]},
 'AUS': {'area_km2': 7692024,
         'domains': ['.au'],
         'calling_codes': ['+61'],
         'landmarks': [{'name': 'Kakadu National Park', 'source': 'https://whc.unesco.org/en/list/147/'},
                       {'name': 'Great Barrier Reef', 'source': 'https://whc.unesco.org/en/list/154/'},
                       {'name': 'Willandra Lakes Region', 'source': 'https://whc.unesco.org/en/list/167/'}]},
 'BLZ': {'area_km2': 22966,
         'domains': ['.bz'],
         'calling_codes': ['+501'],
         'landmarks': [{'name': 'Belize Barrier Reef Reserve System',
                        'source': 'https://whc.unesco.org/en/list/764/'}]},
 'BOL': {'area_km2': 1098581,
         'domains': ['.bo'],
         'calling_codes': ['+591'],
         'landmarks': [{'name': 'City of Potosí', 'source': 'https://whc.unesco.org/en/list/420/'},
                       {'name': 'Jesuit Missions of the Chiquitos',
                        'source': 'https://whc.unesco.org/en/list/529/'},
                       {'name': 'Historic City of Sucre', 'source': 'https://whc.unesco.org/en/list/566/'}]},
 'BRA': {'area_km2': 8515767,
         'domains': ['.br'],
         'calling_codes': ['+55'],
         'landmarks': [{'name': 'Historic Town of Ouro Preto', 'source': 'https://whc.unesco.org/en/list/124/'},
                       {'name': 'Historic Centre of the Town of Olinda',
                        'source': 'https://whc.unesco.org/en/list/189/'},
                       {'name': 'Historic Centre of Salvador de Bahia',
                        'source': 'https://whc.unesco.org/en/list/309/'}]},
 'BTN': {'area_km2': 38394, 'domains': ['.bt'], 'calling_codes': ['+975'], 'landmarks': []},
 'BWA': {'area_km2': 582000,
         'domains': ['.bw'],
         'calling_codes': ['+267'],
         'landmarks': [{'name': 'Tsodilo', 'source': 'https://whc.unesco.org/en/list/1021/'},
                       {'name': 'Okavango Delta', 'source': 'https://whc.unesco.org/en/list/1432/'}]},
 'CAN': {'area_km2': 9984670,
         'domains': ['.ca'],
         'calling_codes': [],
         'landmarks': [{'name': 'L’Anse aux Meadows National Historic Site',
                        'source': 'https://whc.unesco.org/en/list/4/'},
                       {'name': 'Nahanni National Park', 'source': 'https://whc.unesco.org/en/list/24/'},
                       {'name': 'Dinosaur Provincial Park', 'source': 'https://whc.unesco.org/en/list/71/'}]},
 'CHL': {'area_km2': 756102,
         'domains': ['.cl'],
         'calling_codes': ['+56'],
         'landmarks': [{'name': 'Rapa Nui National Park', 'source': 'https://whc.unesco.org/en/list/715/'},
                       {'name': 'Churches of Chiloé', 'source': 'https://whc.unesco.org/en/list/971/'},
                       {'name': 'Historic Quarter of the Seaport City of Valparaíso',
                        'source': 'https://whc.unesco.org/en/list/959/'}]},
 'CHN': {'area_km2': 9706961,
         'domains': ['.cn', '.中国', '.中國', '.公司', '.网络'],
         'calling_codes': ['+86'],
         'landmarks': [{'name': 'Mount Taishan', 'source': 'https://whc.unesco.org/en/list/437/'},
                       {'name': 'The Great Wall', 'source': 'https://whc.unesco.org/en/list/438/'},
                       {'name': 'Imperial Palaces of the Ming and Qing Dynasties in Beijing and Shenyang',
                        'source': 'https://whc.unesco.org/en/list/439/'}]},
 'COL': {'area_km2': 1141748,
         'domains': ['.co'],
         'calling_codes': ['+57'],
         'landmarks': [{'name': 'Port, Fortresses and Group of Monuments, Cartagena',
                        'source': 'https://whc.unesco.org/en/list/285/'},
                       {'name': 'Los Katíos National Park', 'source': 'https://whc.unesco.org/en/list/711/'},
                       {'name': 'Historic Centre of Santa Cruz de Mompox',
                        'source': 'https://whc.unesco.org/en/list/742/'}]},
 'COM': {'area_km2': 1862,
         'domains': ['.km'],
         'calling_codes': ['+269'],
         'landmarks': [{'name': 'The Medinas of the Historic Sultanates of the Comoros',
                        'source': 'https://whc.unesco.org/en/list/1768/'}]},
 'CPV': {'area_km2': 4033,
         'domains': ['.cv'],
         'calling_codes': ['+238'],
         'landmarks': [{'name': 'Cidade Velha, Historic Centre of Ribeira Grande',
                        'source': 'https://whc.unesco.org/en/list/1310/'}]},
 'CRI': {'area_km2': 51100,
         'domains': ['.cr'],
         'calling_codes': ['+506'],
         'landmarks': [{'name': 'Cocos Island National Park', 'source': 'https://whc.unesco.org/en/list/820/'},
                       {'name': 'Area de Conservación Guanacaste',
                        'source': 'https://whc.unesco.org/en/list/928/'},
                       {'name': 'Precolumbian Chiefdom Settlements with Stone Spheres of the Diquís',
                        'source': 'https://whc.unesco.org/en/list/1453/'}]},
 'CUB': {'area_km2': 109884,
         'domains': ['.cu'],
         'calling_codes': ['+53'],
         'landmarks': [{'name': 'Old Havana and its Fortification System',
                        'source': 'https://whc.unesco.org/en/list/204/'},
                       {'name': 'Trinidad and the Valley de los Ingenios',
                        'source': 'https://whc.unesco.org/en/list/460/'},
                       {'name': 'San Pedro de la Roca Castle, Santiago de Cuba',
                        'source': 'https://whc.unesco.org/en/list/841/'}]},
 'DEU': {'area_km2': 357114,
         'domains': ['.de'],
         'calling_codes': ['+49'],
         'landmarks': [{'name': 'Aachen Cathedral', 'source': 'https://whc.unesco.org/en/list/3/'},
                       {'name': 'Speyer Cathedral', 'source': 'https://whc.unesco.org/en/list/168/'},
                       {'name': 'Würzburg Residence with the Court Gardens and Residence Square',
                        'source': 'https://whc.unesco.org/en/list/169/'}]},
 'DMA': {'area_km2': 751,
         'domains': ['.dm'],
         'calling_codes': ['+1767'],
         'landmarks': [{'name': 'Morne Trois Pitons National Park',
                        'source': 'https://whc.unesco.org/en/list/814/'}]},
 'EGY': {'area_km2': 1002450,
         'domains': ['.eg', '.مصر'],
         'calling_codes': ['+20'],
         'landmarks': [{'name': 'Memphis and its Necropolis – the Pyramid Fields from Giza to Dahshur',
                        'source': 'https://whc.unesco.org/en/list/86/'},
                       {'name': 'Ancient Thebes with its Necropolis',
                        'source': 'https://whc.unesco.org/en/list/87/'},
                       {'name': 'Nubian Monuments from Abu Simbel to Philae',
                        'source': 'https://whc.unesco.org/en/list/88/'}]},
 'ESP': {'area_km2': 505992,
         'domains': ['.es'],
         'calling_codes': ['+34'],
         'landmarks': [{'name': 'Historic Centre of Cordoba', 'source': 'https://whc.unesco.org/en/list/313/'},
                       {'name': 'Alhambra, Generalife and Albayzín, Granada',
                        'source': 'https://whc.unesco.org/en/list/314/'},
                       {'name': 'Burgos Cathedral', 'source': 'https://whc.unesco.org/en/list/316/'}]},
 'EST': {'area_km2': 45227,
         'domains': ['.ee'],
         'calling_codes': ['+372'],
         'landmarks': [{'name': 'Historic Centre (Old Town) of Tallinn',
                        'source': 'https://whc.unesco.org/en/list/822/'}]},
 'FJI': {'area_km2': 18272,
         'domains': ['.fj'],
         'calling_codes': ['+679'],
         'landmarks': [{'name': 'Levuka Historical Port Town', 'source': 'https://whc.unesco.org/en/list/1399/'}]},
 'FRA': {'area_km2': 551695,
         'domains': ['.fr'],
         'calling_codes': ['+33'],
         'landmarks': [{'name': 'Mont-Saint-Michel and its Bay', 'source': 'https://whc.unesco.org/en/list/80/'},
                       {'name': 'Chartres Cathedral', 'source': 'https://whc.unesco.org/en/list/81/'},
                       {'name': 'Palace and Park of Versailles', 'source': 'https://whc.unesco.org/en/list/83/'}]},
 'FSM': {'area_km2': 702,
         'domains': ['.fm'],
         'calling_codes': ['+691'],
         'landmarks': [{'name': 'Nan Madol: Ceremonial Centre of Eastern Micronesia',
                        'source': 'https://whc.unesco.org/en/list/1503/'}]},
 'GHA': {'area_km2': 238533,
         'domains': ['.gh'],
         'calling_codes': ['+233'],
         'landmarks': [{'name': 'Forts and Castles, Volta, Greater Accra, Central and Western Regions',
                        'source': 'https://whc.unesco.org/en/list/34/'},
                       {'name': 'Asante Traditional Buildings', 'source': 'https://whc.unesco.org/en/list/35/'}]},
 'GRD': {'area_km2': 344, 'domains': ['.gd'], 'calling_codes': ['+1473'], 'landmarks': []},
 'GTM': {'area_km2': 108889,
         'domains': ['.gt'],
         'calling_codes': ['+502'],
         'landmarks': [{'name': 'Tikal National Park', 'source': 'https://whc.unesco.org/en/list/64/'},
                       {'name': 'Antigua Guatemala', 'source': 'https://whc.unesco.org/en/list/65/'},
                       {'name': 'Archaeological Park and Ruins of Quirigua',
                        'source': 'https://whc.unesco.org/en/list/149/'}]},
 'GUY': {'area_km2': 214969, 'domains': ['.gy'], 'calling_codes': ['+592'], 'landmarks': []},
 'HND': {'area_km2': 112492,
         'domains': ['.hn'],
         'calling_codes': ['+504'],
         'landmarks': [{'name': 'Maya Site of Copan', 'source': 'https://whc.unesco.org/en/list/129/'},
                       {'name': 'Río Plátano Biosphere Reserve',
                        'source': 'https://whc.unesco.org/en/list/196/'}]},
 'IND': {'area_km2': 3287590,
         'domains': ['.in'],
         'calling_codes': ['+91'],
         'landmarks': [{'name': 'Ajanta Caves', 'source': 'https://whc.unesco.org/en/list/242/'},
                       {'name': 'Ellora Caves', 'source': 'https://whc.unesco.org/en/list/243/'},
                       {'name': 'Agra Fort', 'source': 'https://whc.unesco.org/en/list/251/'}]},
 'ITA': {'area_km2': 301336,
         'domains': ['.it'],
         'calling_codes': ['+39'],
         'landmarks': [{'name': 'Rock Drawings in Valcamonica', 'source': 'https://whc.unesco.org/en/list/94/'},
                       {'name': 'Church and Dominican Convent of Santa Maria delle Grazie with “The Last Supper” '
                                'by Leonardo da Vinci',
                        'source': 'https://whc.unesco.org/en/list/93/'},
                       {'name': 'Historic Centre of Florence', 'source': 'https://whc.unesco.org/en/list/174/'}]},
 'JAM': {'area_km2': 10991,
         'domains': ['.jm'],
         'calling_codes': ['+1876'],
         'landmarks': [{'name': 'Blue and John Crow Mountains', 'source': 'https://whc.unesco.org/en/list/1356/'},
                       {'name': 'The Archaeological Ensemble of 17th Century Port Royal',
                        'source': 'https://whc.unesco.org/en/list/1595/'}]},
 'JPN': {'area_km2': 377930,
         'domains': ['.jp', '.みんな'],
         'calling_codes': ['+81'],
         'landmarks': [{'name': 'Buddhist Monuments in the Horyu-ji Area',
                        'source': 'https://whc.unesco.org/en/list/660/'},
                       {'name': 'Himeji-jo', 'source': 'https://whc.unesco.org/en/list/661/'},
                       {'name': 'Yakushima', 'source': 'https://whc.unesco.org/en/list/662/'}]},
 'KEN': {'area_km2': 580367,
         'domains': ['.ke'],
         'calling_codes': ['+254'],
         'landmarks': [{'name': 'Mount Kenya National Park/Natural Forest',
                        'source': 'https://whc.unesco.org/en/list/800/'},
                       {'name': 'Lake Turkana National Parks', 'source': 'https://whc.unesco.org/en/list/801/'},
                       {'name': 'Lamu Old Town', 'source': 'https://whc.unesco.org/en/list/1055/'}]},
 'KHM': {'area_km2': 181035,
         'domains': ['.kh'],
         'calling_codes': ['+855'],
         'landmarks': [{'name': 'Angkor', 'source': 'https://whc.unesco.org/en/list/668/'},
                       {'name': 'Temple of Preah Vihear', 'source': 'https://whc.unesco.org/en/list/1224/'},
                       {'name': 'Temple Zone of Sambor Prei Kuk, Archaeological Site of Ancient Ishanapura',
                        'source': 'https://whc.unesco.org/en/list/1532/'}]},
 'KIR': {'area_km2': 811,
         'domains': ['.ki'],
         'calling_codes': ['+686'],
         'landmarks': [{'name': 'Phoenix Islands Protected Area',
                        'source': 'https://whc.unesco.org/en/list/1325/'}]},
 'KNA': {'area_km2': 261,
         'domains': ['.kn'],
         'calling_codes': ['+1869'],
         'landmarks': [{'name': 'Brimstone Hill Fortress National Park',
                        'source': 'https://whc.unesco.org/en/list/910/'}]},
 'LAO': {'area_km2': 236800,
         'domains': ['.la'],
         'calling_codes': ['+856'],
         'landmarks': [{'name': 'Town of Luang Prabang', 'source': 'https://whc.unesco.org/en/list/479/'},
                       {'name': 'Vat Phou and Associated Ancient Settlements within the Champasak Cultural '
                                'Landscape',
                        'source': 'https://whc.unesco.org/en/list/481/'},
                       {'name': 'Megalithic Jar Sites in Xiengkhuang – Plain of Jars',
                        'source': 'https://whc.unesco.org/en/list/1587/'}]},
 'LCA': {'area_km2': 616,
         'domains': ['.lc'],
         'calling_codes': ['+1758'],
         'landmarks': [{'name': 'Pitons Management Area', 'source': 'https://whc.unesco.org/en/list/1161/'}]},
 'LIE': {'area_km2': 160, 'domains': ['.li'], 'calling_codes': ['+423'], 'landmarks': []},
 'LKA': {'area_km2': 65610,
         'domains': ['.lk', '.இலங்கை', '.ලංකා'],
         'calling_codes': ['+94'],
         'landmarks': [{'name': 'Sacred City of Anuradhapura', 'source': 'https://whc.unesco.org/en/list/200/'},
                       {'name': 'Ancient City of Polonnaruwa', 'source': 'https://whc.unesco.org/en/list/201/'},
                       {'name': 'Ancient City of Sigiriya', 'source': 'https://whc.unesco.org/en/list/202/'}]},
 'LSO': {'area_km2': 30355, 'domains': ['.ls'], 'calling_codes': ['+266'], 'landmarks': []},
 'LTU': {'area_km2': 65300,
         'domains': ['.lt'],
         'calling_codes': ['+370'],
         'landmarks': [{'name': 'Vilnius Historic Centre', 'source': 'https://whc.unesco.org/en/list/541/'},
                       {'name': 'Kernavė Archaeological Site (Cultural Reserve of Kernavė)',
                        'source': 'https://whc.unesco.org/en/list/1137/'},
                       {'name': 'Modernist Kaunas: Architecture of Optimism, 1919-1939',
                        'source': 'https://whc.unesco.org/en/list/1661/'}]},
 'LUX': {'area_km2': 2586,
         'domains': ['.lu'],
         'calling_codes': ['+352'],
         'landmarks': [{'name': 'City of Luxembourg: its Old Quarters and Fortifications',
                        'source': 'https://whc.unesco.org/en/list/699/'}]},
 'LVA': {'area_km2': 64559,
         'domains': ['.lv'],
         'calling_codes': ['+371'],
         'landmarks': [{'name': 'Historic Centre of Riga', 'source': 'https://whc.unesco.org/en/list/852/'},
                       {'name': 'Old town of Kuldīga', 'source': 'https://whc.unesco.org/en/list/1658/'}]},
 'MDA': {'area_km2': 33846, 'domains': ['.md'], 'calling_codes': ['+373'], 'landmarks': []},
 'MDG': {'area_km2': 587041,
         'domains': ['.mg'],
         'calling_codes': ['+261'],
         'landmarks': [{'name': 'Andrefana Dry Forests', 'source': 'https://whc.unesco.org/en/list/494/'},
                       {'name': 'Royal Hill of Ambohimanga', 'source': 'https://whc.unesco.org/en/list/950/'},
                       {'name': 'Rainforests of the Atsinanana',
                        'source': 'https://whc.unesco.org/en/list/1257/'}]},
 'MDV': {'area_km2': 300, 'domains': ['.mv'], 'calling_codes': ['+960'], 'landmarks': []},
 'MEX': {'area_km2': 1964375,
         'domains': ['.mx'],
         'calling_codes': ['+52'],
         'landmarks': [{'name': "Sian Ka'an", 'source': 'https://whc.unesco.org/en/list/410/'},
                       {'name': 'Pre-Hispanic City and National Park of Palenque',
                        'source': 'https://whc.unesco.org/en/list/411/'},
                       {'name': 'Historic Centre of Mexico City and Xochimilco',
                        'source': 'https://whc.unesco.org/en/list/412/'}]},
 'MHL': {'area_km2': 181,
         'domains': ['.mh'],
         'calling_codes': ['+692'],
         'landmarks': [{'name': 'Bikini Atoll Nuclear Test Site',
                        'source': 'https://whc.unesco.org/en/list/1339/'}]},
 'MKD': {'area_km2': 25713, 'domains': ['.mk'], 'calling_codes': ['+389'], 'landmarks': []},
 'MLT': {'area_km2': 316,
         'domains': ['.mt'],
         'calling_codes': ['+356'],
         'landmarks': [{'name': 'Ħal Saflieni Hypogeum', 'source': 'https://whc.unesco.org/en/list/130/'},
                       {'name': 'City of Valletta', 'source': 'https://whc.unesco.org/en/list/131/'},
                       {'name': 'Megalithic Temples of Malta', 'source': 'https://whc.unesco.org/en/list/132/'}]},
 'MNG': {'area_km2': 1564110,
         'domains': ['.mn'],
         'calling_codes': ['+976'],
         'landmarks': [{'name': 'Orkhon Valley Cultural Landscape',
                        'source': 'https://whc.unesco.org/en/list/1081/'},
                       {'name': 'Petroglyphic Complexes of the Mongolian Altai',
                        'source': 'https://whc.unesco.org/en/list/1382/'},
                       {'name': 'Great Burkhan Khaldun Mountain and its surrounding sacred landscape',
                        'source': 'https://whc.unesco.org/en/list/1440/'}]},
 'MUS': {'area_km2': 2040,
         'domains': ['.mu'],
         'calling_codes': ['+230'],
         'landmarks': [{'name': 'Aapravasi Ghat', 'source': 'https://whc.unesco.org/en/list/1227/'},
                       {'name': 'Le Morne Cultural Landscape', 'source': 'https://whc.unesco.org/en/list/1259/'}]},
 'NAM': {'area_km2': 825615,
         'domains': ['.na'],
         'calling_codes': ['+264'],
         'landmarks': [{'name': 'Twyfelfontein or /Ui-//aes', 'source': 'https://whc.unesco.org/en/list/1255/'},
                       {'name': 'Namib Sand Sea', 'source': 'https://whc.unesco.org/en/list/1430/'}]},
 'NGA': {'area_km2': 923768,
         'domains': ['.ng'],
         'calling_codes': ['+234'],
         'landmarks': [{'name': 'Sukur Cultural Landscape', 'source': 'https://whc.unesco.org/en/list/938/'},
                       {'name': 'Osun-Osogbo Sacred Grove', 'source': 'https://whc.unesco.org/en/list/1118/'}]},
 'NIC': {'area_km2': 130373,
         'domains': ['.ni'],
         'calling_codes': ['+505'],
         'landmarks': [{'name': 'Ruins of León Viejo', 'source': 'https://whc.unesco.org/en/list/613/'},
                       {'name': 'León Cathedral', 'source': 'https://whc.unesco.org/en/list/1236/'}]},
 'NPL': {'area_km2': 147181,
         'domains': ['.np'],
         'calling_codes': ['+977'],
         'landmarks': [{'name': 'Sagarmatha National Park', 'source': 'https://whc.unesco.org/en/list/120/'},
                       {'name': 'Kathmandu Valley', 'source': 'https://whc.unesco.org/en/list/121/'},
                       {'name': 'Chitwan National Park', 'source': 'https://whc.unesco.org/en/list/284/'}]},
 'NZL': {'area_km2': 270467,
         'domains': ['.nz'],
         'calling_codes': ['+64'],
         'landmarks': [{'name': 'Tongariro National Park', 'source': 'https://whc.unesco.org/en/list/421/'},
                       {'name': 'Te Wahipounamu – South West New Zealand',
                        'source': 'https://whc.unesco.org/en/list/551/'},
                       {'name': 'New Zealand Sub-Antarctic Islands',
                        'source': 'https://whc.unesco.org/en/list/877/'}]},
 'PAK': {'area_km2': 881912,
         'domains': ['.pk'],
         'calling_codes': ['+92'],
         'landmarks': [{'name': 'Archaeological Ruins at Moenjodaro',
                        'source': 'https://whc.unesco.org/en/list/138/'},
                       {'name': 'Taxila', 'source': 'https://whc.unesco.org/en/list/139/'},
                       {'name': 'Buddhist Ruins of Takht-i-Bahi and Neighbouring City Remains at Sahr-i-Bahlol',
                        'source': 'https://whc.unesco.org/en/list/140/'}]},
 'PER': {'area_km2': 1285216,
         'domains': ['.pe'],
         'calling_codes': ['+51'],
         'landmarks': [{'name': 'City of Cuzco', 'source': 'https://whc.unesco.org/en/list/273/'},
                       {'name': 'Historic Sanctuary of Machu Picchu',
                        'source': 'https://whc.unesco.org/en/list/274/'},
                       {'name': 'Chavin (Archaeological Site)', 'source': 'https://whc.unesco.org/en/list/330/'}]},
 'PLW': {'area_km2': 459,
         'domains': ['.pw'],
         'calling_codes': ['+680'],
         'landmarks': [{'name': 'Rock Islands Southern Lagoon',
                        'source': 'https://whc.unesco.org/en/list/1386/'}]},
 'PNG': {'area_km2': 462840,
         'domains': ['.pg'],
         'calling_codes': ['+675'],
         'landmarks': [{'name': 'Kuk Early Agricultural Site', 'source': 'https://whc.unesco.org/en/list/887/'}]},
 'PRT': {'area_km2': 92090,
         'domains': ['.pt'],
         'calling_codes': ['+351'],
         'landmarks': [{'name': 'Central Zone of the Town of Angra do Heroismo in the Azores',
                        'source': 'https://whc.unesco.org/en/list/206/'},
                       {'name': 'Monastery of the Hieronymites and Tower of Belém in Lisbon',
                        'source': 'https://whc.unesco.org/en/list/263/'},
                       {'name': 'Monastery of Batalha', 'source': 'https://whc.unesco.org/en/list/264/'}]},
 'PRY': {'area_km2': 406752,
         'domains': ['.py'],
         'calling_codes': ['+595'],
         'landmarks': [{'name': 'Jesuit Missions of La Santísima Trinidad de Paraná and Jesús de Tavarangue',
                        'source': 'https://whc.unesco.org/en/list/648/'}]},
 'SEN': {'area_km2': 196722,
         'domains': ['.sn'],
         'calling_codes': ['+221'],
         'landmarks': [{'name': 'Island of Gorée', 'source': 'https://whc.unesco.org/en/list/26/'},
                       {'name': 'Djoudj National Bird Sanctuary', 'source': 'https://whc.unesco.org/en/list/25/'},
                       {'name': 'Niokolo-Koba National Park', 'source': 'https://whc.unesco.org/en/list/153/'}]},
 'SLB': {'area_km2': 28896,
         'domains': ['.sb'],
         'calling_codes': ['+677'],
         'landmarks': [{'name': 'East Rennell', 'source': 'https://whc.unesco.org/en/list/854/'}]},
 'SMR': {'area_km2': 61,
         'domains': ['.sm'],
         'calling_codes': ['+378'],
         'landmarks': [{'name': 'San Marino Historic Centre and Mount Titano',
                        'source': 'https://whc.unesco.org/en/list/1245/'}]},
 'STP': {'area_km2': 964,
         'domains': ['.st'],
         'calling_codes': ['+239'],
         'landmarks': [{'name': 'The Roças of Sao Tome and Principe: Colonial Agricultural System and Forced '
                                'Migration',
                        'source': 'https://whc.unesco.org/en/list/1750/'}]},
 'SUR': {'area_km2': 163820,
         'domains': ['.sr'],
         'calling_codes': ['+597'],
         'landmarks': [{'name': 'Central Suriname Nature Reserve',
                        'source': 'https://whc.unesco.org/en/list/1017/'},
                       {'name': 'Historic Inner City of Paramaribo',
                        'source': 'https://whc.unesco.org/en/list/940/'},
                       {'name': 'Jodensavanne Archaeological Site: Jodensavanne Settlement and Cassipora Creek '
                                'Cemetery',
                        'source': 'https://whc.unesco.org/en/list/1680/'}]},
 'SVN': {'area_km2': 20273,
         'domains': ['.si'],
         'calling_codes': ['+386'],
         'landmarks': [{'name': 'Škocjan Caves', 'source': 'https://whc.unesco.org/en/list/390/'},
                       {'name': 'The works of Jože Plečnik in Ljubljana – Human Centred Urban Design',
                        'source': 'https://whc.unesco.org/en/list/1643/'}]},
 'SWZ': {'area_km2': 17364, 'domains': ['.sz'], 'calling_codes': ['+268'], 'landmarks': []},
 'SYC': {'area_km2': 452,
         'domains': ['.sc'],
         'calling_codes': ['+248'],
         'landmarks': [{'name': 'Aldabra Atoll', 'source': 'https://whc.unesco.org/en/list/185/'},
                       {'name': 'Vallée de Mai Nature Reserve', 'source': 'https://whc.unesco.org/en/list/261/'}]},
 'THA': {'area_km2': 513120,
         'domains': ['.th', '.ไทย'],
         'calling_codes': ['+66'],
         'landmarks': [{'name': 'Historic Town of Sukhothai and Associated Historic Towns',
                        'source': 'https://whc.unesco.org/en/list/574/'},
                       {'name': 'Historic City of Ayutthaya', 'source': 'https://whc.unesco.org/en/list/576/'},
                       {'name': 'Thungyai-Huai Kha Khaeng Wildlife Sanctuaries',
                        'source': 'https://whc.unesco.org/en/list/591/'}]},
 'TLS': {'area_km2': 14874, 'domains': ['.tl'], 'calling_codes': ['+670'], 'landmarks': []},
 'TON': {'area_km2': 747, 'domains': ['.to'], 'calling_codes': ['+676'], 'landmarks': []},
 'TTO': {'area_km2': 5130, 'domains': ['.tt'], 'calling_codes': ['+1868'], 'landmarks': []},
 'TUV': {'area_km2': 26, 'domains': ['.tv'], 'calling_codes': ['+688'], 'landmarks': []},
 'URY': {'area_km2': 181034,
         'domains': ['.uy'],
         'calling_codes': ['+598'],
         'landmarks': [{'name': 'Historic Quarter of the City of Colonia del Sacramento',
                        'source': 'https://whc.unesco.org/en/list/747/'},
                       {'name': 'Fray Bentos Industrial Landscape',
                        'source': 'https://whc.unesco.org/en/list/1464/'},
                       {'name': 'The work of engineer Eladio Dieste: Church of Atlántida',
                        'source': 'https://whc.unesco.org/en/list/1612/'}]},
 'USA': {'area_km2': 9372610,
         'domains': ['.us'],
         'calling_codes': [],
         'landmarks': [{'name': 'Mesa Verde National Park', 'source': 'https://whc.unesco.org/en/list/27/'},
                       {'name': 'Yellowstone National Park', 'source': 'https://whc.unesco.org/en/list/28/'},
                       {'name': 'Grand Canyon National Park', 'source': 'https://whc.unesco.org/en/list/75/'}]},
 'VCT': {'area_km2': 389, 'domains': ['.vc'], 'calling_codes': ['+1784'], 'landmarks': []},
 'VNM': {'area_km2': 331212,
         'domains': ['.vn'],
         'calling_codes': ['+84'],
         'landmarks': [{'name': 'Complex of Hué Monuments', 'source': 'https://whc.unesco.org/en/list/678/'},
                       {'name': 'Ha Long Bay - Cat Ba Archipelago',
                        'source': 'https://whc.unesco.org/en/list/672/'},
                       {'name': 'Hoi An Ancient Town', 'source': 'https://whc.unesco.org/en/list/948/'}]},
 'VUT': {'area_km2': 12189,
         'domains': ['.vu'],
         'calling_codes': ['+678'],
         'landmarks': [{'name': 'Chief Roi Mata’s Domain', 'source': 'https://whc.unesco.org/en/list/1280/'}]},
 'WSM': {'area_km2': 2842, 'domains': ['.ws'], 'calling_codes': ['+685'], 'landmarks': []}}
for _country in COUNTRIES:
    _country.update(COUNTRY_DETAILS.get(_country["id"], {}))

def normalize_country(record):
    if not isinstance(record, dict) or not record.get("id") or not record.get("name") or not record.get("continent"):
        return None
    c = dict(record)
    c["capitals"] = [dict(x, role=x.get("role", "capital")) for x in (c.get("capitals") or [])
                     if isinstance(x, dict) and x.get("name")]
    c["currencies"] = [x for x in (c.get("currencies") or []) if isinstance(x, dict) and x.get("name") and x.get("code")]
    for field in ["languages", "official_languages", "borders"]:
        c[field] = list(dict.fromkeys(x for x in (c.get(field) or []) if isinstance(x, str) and x))
    c["region"] = c.get("region") or ""
    c["source"] = c.get("source") or "https://github.com/mledoze/countries"
    c["tier"] = c.get("tier") if c.get("tier") in (1, 2, 3) else 3
    return c


COUNTRIES = [c for row in COUNTRIES if (c := normalize_country(row)) is not None]

# --- Country lookup and question generation ---
CONTINENTS = ["Africa", "Asia", "Europe", "North America", "South America", "Oceania"]
AREAS = ["World"] + CONTINENTS
CATEGORIES = ["Mixed", "Capitals", "Heads of State", "Currency", "Languages",
              "Country Identification", "Geography / General Facts", "Continents", "True or False", "Landmarks"]
DIFFICULTIES = ["Easy", "Medium", "Difficult", "Expert"]
QUESTION_COUNTS = [5, 10, 15, 20, 25, 50]
DIFFICULTY_MULTIPLIERS = {"Easy": 1.0, "Medium": 1.25, "Difficult": 1.5, "Expert": 2.0}
COUNTRY_BY_ID = {row["id"]: row for row in COUNTRIES}
POLITICAL_MAX_AGE_DAYS = 30


def get_countries(continent="World", country_id="all"):
    return [c for c in COUNTRIES if (continent in ("World", "Whole World") or c["continent"] == continent)
            and (country_id == "all" or c["id"] == country_id)]


def get_country(country_id):
    return COUNTRY_BY_ID.get(country_id)


def valid_political_record(record, today=None):
    try:
        checked = date.fromisoformat(record["verified_on"])
        age = ((today or date.today()) - checked).days
        return (bool(record.get("names")) and isinstance(record["names"], list)
                and all(isinstance(n, str) and n.strip() for n in record["names"])
                and bool(record.get("title")) and str(record.get("source", "")).startswith("https://")
                and 0 <= age <= POLITICAL_MAX_AGE_DAYS)
    except (KeyError, TypeError, ValueError):
        return False


def load_political_records():
    """An optional local JSON file can update leaders without editing quiz logic."""
    records = dict(HEADS_OF_STATE)
    override = Path(__file__).with_name("heads_of_state.json")
    if override.exists():
        try:
            data = json.loads(override.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                records.update({k: v for k, v in data.items() if k in COUNTRY_BY_ID and isinstance(v, dict)})
        except (OSError, ValueError, TypeError):
            pass
    return {k: v for k, v in records.items() if valid_political_record(v)}


def plausible_choices(country, field, correct, valid_answers, difficulty, rng):
    """Exclude every valid answer, not just the one selected as correct."""
    buckets = [[], [], [], []]
    for other in COUNTRIES:
        if field == "capital":
            values = [item["name"] for item in other.get("capitals", [])]
        elif field == "currency":
            values = [f"{item['name']} ({item['code']})" for item in other.get("currencies", [])]
        elif field == "language":
            values = other.get("official_languages", [])
        elif field == "country":
            values = [other["name"]]
        elif field == "region":
            values = [other.get("region", "")]
        else:
            values = []
        bucket = (0 if other["id"] in country.get("borders", []) else
                  1 if other.get("region") == country.get("region") else
                  2 if other["continent"] == country["continent"] else 3)
        for value in values:
            if value and value not in valid_answers:
                buckets[bucket].append(value)
    if difficulty == "Easy":
        buckets = [sum(buckets, [])]
    distractors = []
    for bucket in buckets:
        unique = list(dict.fromkeys(bucket))
        rng.shuffle(unique)
        for value in unique:
            if value not in distractors:
                distractors.append(value)
        if len(distractors) >= 3:
            break
    if len(distractors) < 3:
        return None
    choices = distractors[:3] + [correct]
    rng.shuffle(choices)
    return choices


def question_candidates(country, category, difficulty, rng, leaders):
    name = country["name"]
    capitals = [x["name"] for x in country.get("capitals", [])]
    currencies = [f"{x['name']} ({x['code']})" for x in country.get("currencies", [])]
    languages = list(country.get("official_languages", []))
    rng.shuffle(languages)
    rng.shuffle(currencies)
    result = []

    def add(suffix, kind, prompt, answer, options, explanation, source=None, facts=None, family=None):
        if (not options or len(options) not in (2, 4) or len(set(options)) != len(options)
                or options.count(answer) != 1):
            return
        result.append({"id": f"{country['id']}:{suffix}", "country_id": country["id"],
                       "country": name, "kind": kind, "family": family or kind,
                       "facts": facts or [f"{country['id']}:{suffix.split(':')[0]}"],
                       "prompt": prompt, "answer": answer,
                       "choices": options, "explanation": explanation,
                       "source": source or (country.get("capital_source") if kind == "Capitals" or suffix == "truefalse:capital" else None) or country["source"],
                       "extra_source": country.get("capital_source") if kind == "Country Identification" else None})

    if category in ("Mixed", "Capitals"):
        for capital in country.get("capitals", []):
            role = capital.get("role", "capital")
            answer = capital["name"]
            prompt = f"Which place serves as the {role} of {name}?"
            options = plausible_choices(country, "capital", answer, capitals, difficulty, rng)
            add(f"capital:{answer}", "Capitals", prompt, answer, options,
                f"{answer} is the {role} of {name}.", facts=[f"{country['id']}:capital"])
            if difficulty in ("Difficult", "Expert"):
                options = plausible_choices(country, "country", name, [name], difficulty, rng)
                add(f"reverse:{answer}", "Capitals", f"{answer} is the {role} of which country?",
                    name, options, f"{answer} is the {role} of {name}.", facts=[f"{country['id']}:capital"])
    if category in ("Mixed", "Currency"):
        for currency in currencies:
            options = plausible_choices(country, "currency", currency, currencies, difficulty, rng)
            add(f"currency:{currency}", "Currency", f"Which of these currencies is used in {name}?",
                currency, options, f"{name} uses {', '.join(currencies)}.")
    if category in ("Mixed", "Languages"):
        for language in languages:
            options = plausible_choices(country, "language", language, languages, difficulty, rng)
            add(f"language:{language}", "Languages", f"Which of these is an official language of {name}?",
                language, options, f"{language} is an official language of {name}.",
                source="https://ungegn.un.org/dashboard/countries/details?id=4" if country["id"] == "AFG" else None)
    if category in ("Mixed", "Country Identification") and capitals:
        answer = name
        options = plausible_choices(country, "country", answer, [answer], difficulty, rng)
        clue = f"Its {country['capitals'][0].get('role', 'capital')} is {capitals[0]}"
        if difficulty in ("Difficult", "Expert") and currencies:
            clue += f", and it uses {currencies[0]}"
        if difficulty == "Expert" and languages:
            clue += f". {languages[0]} is one of its official languages"
        add("identify", "Country Identification", f"Identify the country: {clue}.",
            answer, options, f"These clues describe {name}.",
            facts=[f"{country['id']}:capital"] + ([f"{country['id']}:currency"] if difficulty in ("Difficult", "Expert") and currencies else [])
            + ([f"{country['id']}:language"] if difficulty == "Expert" and languages else []))
    if category in ("Mixed", "Geography / General Facts"):
        region = country.get("region")
        if region:
            options = plausible_choices(country, "region", region, [region], difficulty, rng)
            add("region", "Geography / General Facts", f"In which geographic subregion is {name}?",
                region, options, f"{name} is in {region}, within {country['continent']}.")
        neighbours = [get_country(i) for i in country.get("borders", []) if get_country(i)]
        if neighbours:
            answer = rng.choice(neighbours)["name"]
            valid = [c["name"] for c in neighbours] + [name]
            options = plausible_choices(country, "country", answer, valid, difficulty, rng)
            add("border", "Geography / General Facts", f"Which of these countries shares a land border with {name}?",
                answer, options, f"{answer} and {name} share a land border.",
                facts=["border:" + ":".join(sorted([country["id"], next(c["id"] for c in neighbours if c["name"] == answer)]))], family="Neighbours")
    if category in ("Mixed", "Continents"):
        options = rng.sample([c for c in CONTINENTS if c != country["continent"]], 3) + [country["continent"]]
        rng.shuffle(options)
        add("continent", "Continents", f"On which continent is {name}?", country["continent"],
            options, f"{name} is in {country['continent']}.")
    if category in ("Mixed", "True or False"):
        statements = [(f"{name} is landlocked.", bool(country.get("landlocked")),
                       f"{name} " + ("is landlocked." if country.get("landlocked") else "has a coastline."), "coast")]
        if capitals:
            role = country["capitals"][0].get("role", "capital")
            choices = plausible_choices(country, "capital", capitals[0], capitals, difficulty, rng)
            truthful = rng.choice([True, False])
            if choices:
                stated = capitals[0] if truthful else rng.choice([v for v in choices if v not in capitals])
                statements.append((f"{stated} is the {role} of {name}.", truthful,
                                   f"{capitals[0]} is the {role} of {name}.", "capital"))
        truthful = rng.choice([True, False])
        stated_continent = country["continent"] if truthful else rng.choice([c for c in CONTINENTS if c != country["continent"]])
        statements.append((f"{name} is in {stated_continent}.", truthful,
                           f"{name} is in {country['continent']}.", "continent"))
        for field, values, topic in [("currency", currencies, "currency"), ("language", languages, "language")]:
            if not values:
                continue
            truthful = rng.choice([True, False])
            choices = plausible_choices(country, field, values[0], values, difficulty, rng)
            if not choices:
                continue
            stated = values[0] if truthful else rng.choice([v for v in choices if v not in values])
            statement = (f"{name} uses {stated}." if topic == "currency" else
                         f"{stated} is an official language of {name}.")
            explanation = (f"{name} uses {', '.join(values)}." if topic == "currency" else
                           f"{name}: {', '.join(values)}.")
            statements.append((statement, truthful, explanation, topic))
        for statement, truthful, explanation, topic in statements:
            add("truefalse:" + topic, "True or False", statement, "True" if truthful else "False",
                ["True", "False"], explanation,
                source=("https://ungegn.un.org/dashboard/countries/details?id=4" if country["id"] == "AFG" and topic == "language" else
                        "https://github.com/mledoze/countries" if topic == "coast" else None),
                facts=[f"{country['id']}:{topic}"], family="True or False")
    if category in ("Mixed", "Country Identification"):
        neighbours = [get_country(i) for i in country.get("borders", []) if get_country(i)]
        pairs = [(a, b) for i, a in enumerate(neighbours) for b in neighbours[i + 1:]
                 if [c["id"] for c in COUNTRIES if {a["id"], b["id"]}.issubset(c.get("borders", []))] == [country["id"]]]
        if pairs:
            a, b = rng.choice(pairs)
            options = plausible_choices(country, "country", name, [name], difficulty, rng)
            add("identify-borders", "Country Identification",
                f"Which country shares land borders with both {a['name']} and {b['name']}?",
                name, options, f"{name} shares land borders with {a['name']} and {b['name']}.",
                facts=["border:" + ":".join(sorted([country["id"], n["id"]])) for n in (a, b)],
                family="Neighbour clues")
    if category in ("Mixed", "Landmarks", "Country Identification"):
        for site in country.get("landmarks", []):
            options = plausible_choices(country, "country", name, [name], difficulty, rng)
            add("landmark-reverse:" + site["name"], "Country Identification" if category == "Country Identification" else "Landmarks",
                f"In which country is the UNESCO World Heritage site {site['name']}?",
                name, options, f"{site['name']} is in {name}.", site["source"],
                facts=[f"landmark:{site['name']}"], family="Landmarks")
            alternatives = list({s["name"] for c in COUNTRIES if c["id"] != country["id"]
                                 for s in c.get("landmarks", [])})
            if len(alternatives) >= 3 and category != "Country Identification":
                options = rng.sample(alternatives, 3) + [site["name"]]
                rng.shuffle(options)
                add("landmark:" + site["name"], "Landmarks",
                    f"Which of these UNESCO World Heritage sites is in {name}?",
                    site["name"], options, f"{site['name']} is in {name}.", site["source"],
                    facts=[f"landmark:{site['name']}"], family="Landmarks")
    if category in ("Mixed", "Geography / General Facts"):
        if country.get("area_km2"):
            # Require a substantial size difference so rounding cannot change the answer.
            others = [c for c in COUNTRIES if c["id"] != country["id"] and c.get("area_km2")
                      and max(c["area_km2"], country["area_km2"]) / min(c["area_km2"], country["area_km2"]) > 1.2]
            if others:
                other = rng.choice(others)
                answer = max([country, other], key=lambda c: c["area_km2"])["name"]
                options = [name, other["name"]]
                rng.shuffle(options)
                add("area:" + other["id"], "Geography / General Facts",
                    f"Which country has the larger total area: {name} or {other['name']}?", answer, options,
                    f"{name}: {country['area_km2']:,.0f} km²; {other['name']}: {other['area_km2']:,.0f} km².",
                    source="https://github.com/mledoze/countries",
                    facts=[f"{country['id']}:area", f"{other['id']}:area"], family="Size comparisons")
        for field, label, prompt in [
                ("domains", "Internet domains", f"Which country-code internet domain belongs to {name}?"),
                ("calling_codes", "Calling codes", f"Which international telephone calling code belongs to {name}?")]:
            values = country.get(field, [])
            alternatives = list({v for c in COUNTRIES for v in c.get(field, []) if v not in values})
            if values and len(alternatives) >= 3:
                answer = rng.choice(values)
                options = rng.sample(alternatives, 3) + [answer]
                rng.shuffle(options)
                add(field, "Geography / General Facts", prompt, answer, options,
                    f"{name}: {', '.join(values)}.", source="https://github.com/mledoze/countries", family=label)
    if category in ("Mixed", "Heads of State") and country["id"] in leaders:
        leader = leaders[country["id"]]
        answer = " / ".join(leader["names"])
        valid = {" / ".join(r["names"]) for r in leaders.values()
                 if set(r["names"]) & set(leader["names"])}
        alternatives = list({" / ".join(r["names"]) for r in leaders.values()} - valid)
        rng.shuffle(alternatives)
        if len(alternatives) >= 3:
            options = alternatives[:3] + [answer]
            rng.shuffle(options)
            prompt = (f"Who is the {leader['title']} and head of state of {name}? "
                      f"(Record verified {leader['verified_on']})")
            add("leader", "Heads of State", prompt, answer, options,
                f"{answer} is recorded as {leader['title']} of {name}, verified {leader['verified_on']}. "
                "Head of state and head of government can be different offices.", leader["source"])
    return result


def generate_quiz(settings, recent=None, seed=None, leaders=None, recent_facts=None):
    required = {"continent", "country_id", "category", "difficulty", "count", "timer"}
    if (not isinstance(settings, dict) or not required.issubset(settings)
            or settings["continent"] not in AREAS
            or settings["category"] not in CATEGORIES
            or settings["difficulty"] not in DIFFICULTIES
            or settings["count"] not in QUESTION_COUNTS):
        return [], 0
    rng = random.Random(seed)
    leaders = load_political_records() if leaders is None else leaders
    pool = get_countries(settings["continent"], settings["country_id"])
    candidates = [q for c in pool for q in question_candidates(c, settings["category"], settings["difficulty"], rng, leaders)]
    if settings["country_id"] != "all" and settings["category"] != "Country Identification":
        candidates = [q for q in candidates if ":landmark-reverse:" not in q["id"] and ":reverse:" not in q["id"]]
    candidates = list({q["prompt"]: q for q in candidates}.values())
    rng.shuffle(candidates)
    selected, countries_used, types_used, used_facts = [], Counter(), Counter(), set()
    recent, recent_facts = set(recent or []), set(recent_facts or [])
    # Build a full compatible schedule: its length is the actual capacity,
    # not the number of alternate phrasings of the same underlying fact.
    while candidates:
        candidates.sort(key=lambda q: (
            bool(set(q["facts"]) & recent_facts),
            countries_used[q["country_id"]], types_used[q["family"]],
            q["country_id"] in recent,
            bool(selected and q["family"] == selected[-1]["family"])))
        choice = candidates.pop(0)
        selected.append(choice)
        countries_used[choice["country_id"]] += 1
        types_used[choice["family"]] += 1
        used_facts.update(choice["facts"])
        candidates = [q for q in candidates if not used_facts.intersection(q["facts"])]
    return selected[:settings["count"]], len(selected)


# --- Scoring and game state ---
def score_answer(correct, difficulty, elapsed, streak, used_hint=False, time_limit=None):
    if not correct:
        return {"base": 0, "speed": 0, "streak": 0, "hint": 0, "total": 0}
    base = round(100 * DIFFICULTY_MULTIPLIERS[difficulty])
    speed = 25 if elapsed <= (time_limit / 3 if time_limit else 7) else 0
    bonus = (50 if streak % 3 == 0 else 0) + (100 if streak % 5 == 0 else 0)
    penalty = 25 if used_hint else 0
    return {"base": base, "speed": speed, "streak": bonus, "hint": penalty,
            "total": max(0, base + speed + bonus - penalty)}


def initialise_state():
    defaults = {"points": 0, "streak": 0, "rounds_finished": 0,
                "recent": [], "recent_facts": [], "page": "Explore", "quiz": None, "quiz_serial": 0,
                "show_setup": False, "review_answers": False, "app_language": "English",
                "profile_name": "", "profile_photo": "", "scope_mode": "All countries", "scope_continent": "World",
                "scope_country": "all", "explore_page": 0, "settings_open": False}
    for name, value in defaults.items():
        if name not in st.session_state:
            st.session_state[name] = value


def start_quiz(settings):
    questions, available = generate_quiz(settings, st.session_state.recent, recent_facts=st.session_state.recent_facts)
    if not questions:
        return False
    st.session_state.quiz_serial += 1
    st.session_state.quiz = {
        "settings": dict(settings), "questions": questions, "available": available,
        "index": 0, "selected": None, "resolved": False, "finished": False,
        "score": 0, "correct": 0, "streak": 0, "best_streak": 0,
        "hints_remaining": 3, "hint_used": False, "hidden_options": [],
        "history": [], "started_at": None, "serial": st.session_state.quiz_serial,
        "perfect_bonus": 0, "last_points": None,
    }
    st.session_state.streak = 0
    st.session_state.review_answers = False
    st.session_state.show_setup = False
    return True


def ensure_question_clock(quiz, now=None):
    if quiz["started_at"] is None and not quiz["resolved"] and not quiz["finished"]:
        quiz["started_at"] = time.monotonic() if now is None else now


def question_time_limit(quiz):
    if not quiz["settings"]["timer"]:
        return None
    return 15 if quiz["settings"]["difficulty"] == "Expert" else 20


def question_elapsed(quiz, now=None):
    ensure_question_clock(quiz, now)
    return max(0.0, (time.monotonic() if now is None else now) - quiz["started_at"])


def resolve_answer(choice, serial=None, index=None, now=None):
    quiz = st.session_state.quiz
    if (not quiz or quiz["resolved"] or quiz["finished"] or
            (serial is not None and serial != quiz["serial"]) or
            (index is not None and index != quiz["index"])):
        return
    q = quiz["questions"][quiz["index"]]
    if choice is not None and (choice not in q["choices"] or choice in quiz["hidden_options"]):
        return
    elapsed = question_elapsed(quiz, now)
    limit = question_time_limit(quiz)
    timed_out = limit is not None and elapsed >= limit
    if timed_out:
        choice = None
        elapsed = float(limit)
    quiz["selected"] = choice
    quiz["resolved"] = True
    correct = choice == q["answer"]
    quiz["streak"] = quiz["streak"] + 1 if correct else 0
    quiz["best_streak"] = max(quiz["best_streak"], quiz["streak"])
    quiz["correct"] += int(correct)
    points = score_answer(correct, quiz["settings"]["difficulty"], elapsed,
                          quiz["streak"], quiz["hint_used"], limit)
    quiz["score"] += points["total"]
    quiz["last_points"] = points
    st.session_state.points += points["total"]
    st.session_state.streak = quiz["streak"]
    quiz["history"].append({"question": q, "answer": choice, "correct": correct,
                            "elapsed": elapsed, "hint": quiz["hint_used"],
                            "timed_out": timed_out, "points": points})
    st.session_state.recent = (st.session_state.recent + [q["country_id"]])[-40:]
    st.session_state.recent_facts = (st.session_state.recent_facts + q.get("facts", []))[-160:]


def use_hint(serial, index):
    quiz = st.session_state.quiz
    if (not quiz or quiz["finished"] or quiz["resolved"] or quiz["hint_used"] or
            quiz["hints_remaining"] <= 0 or serial != quiz["serial"] or index != quiz["index"]):
        return
    limit = question_time_limit(quiz)
    if limit is not None and question_elapsed(quiz) >= limit:
        resolve_answer(None, serial, index)
        return
    q = quiz["questions"][quiz["index"]]
    if len(q["choices"]) < 4:
        return
    quiz["hidden_options"] = [random.choice([c for c in q["choices"] if c != q["answer"]])]
    quiz["hint_used"] = True
    quiz["hints_remaining"] -= 1


def advance_question(serial, index):
    quiz = st.session_state.quiz
    if (not quiz or not quiz["resolved"] or quiz["finished"] or
            quiz["serial"] != serial or quiz["index"] != index):
        return
    if index + 1 == len(quiz["questions"]):
        quiz["finished"] = True
        st.session_state.rounds_finished += 1
        if quiz["correct"] == len(quiz["questions"]) and not any(h["hint"] for h in quiz["history"]):
            quiz["perfect_bonus"] = round(250 * DIFFICULTY_MULTIPLIERS[quiz["settings"]["difficulty"]])
            quiz["score"] += quiz["perfect_bonus"]
            st.session_state.points += quiz["perfect_bonus"]
    else:
        quiz["index"] += 1
        quiz["selected"] = None
        quiz["resolved"] = False
        quiz["started_at"] = None
        quiz["hint_used"] = False
        quiz["hidden_options"] = []
        quiz["last_points"] = None


def quiz_statistics(quiz):
    total = len(quiz["questions"])
    history = quiz["history"]
    return {"total": total, "correct": quiz["correct"], "incorrect": len(history) - quiz["correct"],
            "unanswered": sum(h["answer"] is None for h in history),
            "accuracy": 100 * quiz["correct"] / total if total else 0,
            "average_time": sum(h["elapsed"] for h in history) / len(history) if history else 0,
            "best_streak": quiz["best_streak"], "score": quiz["score"]}


def navigate(page):
    st.session_state.page = page


def open_setup():
    st.session_state.show_setup = True
    st.session_state.review_answers = False


def reset_country_selection():
    st.session_state.filter_country = "all"


def html(content):
    st.markdown(localize_html(content), unsafe_allow_html=True)


# --- Streamlit display functions ---
def globe_art():
    # Decorative orbital globe, not a geographic map or selectable map control.
    return ('<svg viewBox="0 0 320 300" fill="none" aria-hidden="true">'
            '<defs><radialGradient id="ocean"><stop stop-color="#399a9a"/>'
            '<stop offset="1" stop-color="#113b53"/></radialGradient></defs>'
            '<circle cx="160" cy="145" r="115" fill="url(#ocean)" stroke="#73bdb9" stroke-width="1.5"/>'
            '<g stroke="#b3e1d3" opacity=".45"><ellipse cx="160" cy="145" rx="54" ry="115"/>'
            '<ellipse cx="160" cy="145" rx="92" ry="115"/>'
            '<ellipse cx="160" cy="145" rx="115" ry="42"/>'
            '<ellipse cx="160" cy="145" rx="115" ry="84"/>'
            '<path d="M45 145h230M160 30v230"/></g>'
            '<ellipse cx="160" cy="145" rx="152" ry="63" transform="rotate(-28 160 145)" '
            'stroke="#e9c17a" stroke-width="1.5" stroke-dasharray="4 6"/>'
            '<circle cx="269" cy="76" r="7" fill="#f3cf84"/>'
            '<circle cx="57" cy="225" r="5" fill="#81d5c5"/>'
            '<circle cx="204" cy="119" r="5" fill="#fff1c4"/>'
            '<circle cx="204" cy="119" r="13" stroke="#fff1c4" opacity=".5"/>'
            '<text x="160" y="289" text-anchor="middle" fill="#aacbd1" font-size="10" '
            'font-family="Segoe UI,Arial" letter-spacing="4">A WORLD TO DISCOVER</text></svg>')


def render_hero(kicker, title, description, tall=False, compact=False):
    variant = " hero-tall" if tall else " hero-compact" if compact else ""
    tags = '' if compact else (f'<div class="hero-tags"><span>{len(COUNTRIES)} countries</span>'
                               '<span>6 continents</span><span>10 quiz categories</span></div>')
    html(f'<section class="hero{variant}"><div class="hero-copy">'
         f'<div class="hero-kicker">{escape(tr(kicker))}</div><div class="hero-title">{escape(tr(title))}</div>'
         f'<div class="hero-description">{escape(tr(description))}</div>{tags}</div>'
         f'<div class="hero-art">{globe_art()}</div></section>')


def render_brand_and_navigation():
    menu, brand, navigation = st.columns([.13, 1, 1.3], vertical_alignment="center")
    with brand:
        with st.container(key="header_brand"):
            html('<div class="brand"><div class="brand-symbol">'
                 '<svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" '
                 'stroke-width="1.4" aria-hidden="true"><circle cx="14" cy="14" r="11"/>'
                 '<ellipse cx="14" cy="14" rx="5" ry="11"/><path d="M3 14h22M5 8h18M5 20h18"/></svg>'
                 '</div><div><div class="brand-name">World Explorer</div>'
                 '<div class="brand-note">For curious minds. Across every border.</div></div></div>')
    with navigation:
        with st.container(key="navigation"):
            for column, name in zip(st.columns(4), ["Explore", "Learn", "Quiz", "Badges"]):
                with column:
                    st.button(tr(name), key=f"nav_{name}", use_container_width=True,
                              type="primary" if st.session_state.page == name else "secondary",
                              on_click=navigate, args=(name,))
    with menu:
        with st.container(key="header_menu"):
            if st.button(tr("☰"), key="settings_menu", help=tr("Settings"), use_container_width=True):
                st.session_state.settings_open = True
    if st.session_state.settings_open:
        open_settings()
    photo = st.session_state.get("profile_photo", "")
    avatar = (f'<img class="header-avatar" src="{escape(photo, quote=True)}" alt="Profile photo">' if photo else
              '<span class="header-avatar default-avatar" aria-label="Guest profile">●</span>')
    label = st.session_state.profile_name or tr("Guest explorer")
    html(f'<div class="profile-note">{avatar}<span>{escape(label)} · {escape(scope_label())}</span></div>')
    st.divider()


def learn_country(country_id):
    st.session_state.learn_country = country_id
    navigate("Learn")


def render_quiz_setup():
    if "filter_continent" not in st.session_state:
        st.session_state.filter_continent = st.session_state.scope_continent
    if "filter_country" not in st.session_state:
        st.session_state.filter_country = st.session_state.scope_country
    with st.container(key="settings_card"):
        html('<div class="eyebrow">Your next adventure</div>')
        st.subheader(tr("Build your challenge"))
        one, two = st.columns(2)
        with one:
            continent = st.selectbox(tr("Continent"), AREAS, format_func=option_formatter(AREAS), key="filter_continent",
                                     on_change=reset_country_selection)
        available_countries = get_countries(continent)
        ids = ["all"] + [c["id"] for c in available_countries]
        if st.session_state.get("filter_country", "all") not in ids:
            st.session_state.filter_country = "all"
        with two:
            country_id = st.selectbox(tr("Country"), ids, key="filter_country",
                                     format_func=lambda i, all_label=tr("All Countries"): all_label if i == "all" else get_country(i)["name"])
        left, right = st.columns(2)
        with left:
            category = st.selectbox(tr("Category"), CATEGORIES, format_func=option_formatter(CATEGORIES), key="filter_category")
            count = st.selectbox(tr("Questions"), QUESTION_COUNTS, index=3, key="filter_count")
        with right:
            difficulty = st.selectbox(tr("Difficulty"), DIFFICULTIES, format_func=option_formatter(DIFFICULTIES), index=3, key="filter_difficulty")
            timer = st.toggle(tr("Timed challenge"), value=False, key="filter_timer",
                              help="15 seconds per question on Expert; 20 seconds on other levels. The clock continues if you leave the quiz page.")
        settings = {"continent": continent, "country_id": country_id, "category": category,
                    "difficulty": difficulty, "count": count, "timer": timer}
        # Deterministic preview; starting still creates a fresh random round.
        preview, capacity = generate_quiz(settings, seed=0)
        st.caption(tr(f"Up to {settings['count']} questions · no repeated facts in the same round."))
        if category == "Heads of State":
            st.caption(tr("Only recently verified political records are included. Coverage is currently limited."))
        if country_id != "all" and difficulty in ("Difficult", "Expert"):
            st.caption(tr("Your chosen country stays selected; difficulty changes question formats and answer choices."))
        if not preview:
            st.info(tr("No verified questions match these filters. Choose Mixed, another country, or a lower difficulty."))
        elif len(preview) < count:
            st.info(tr("Smaller question pools produce shorter rounds to avoid repeating the same facts."))
        if st.button(tr("Start quiz"), key="start_quiz", type="primary", use_container_width=True, disabled=not preview):
            start_quiz(settings)
            st.rerun()
        if st.session_state.quiz:
            if st.button(tr("Return to current round"), use_container_width=True):
                st.session_state.show_setup = False
                st.rerun()
        with st.expander(tr("Scoring and hints")):
            st.write(tr("Correct answers earn 100 base points, multiplied by difficulty: Easy ×1, Medium ×1.25, Difficult ×1.5, Expert ×2."))
            st.write(tr("Fast answers earn 25 extra points. Every third correct answer in a streak adds 50; every fifth adds 100. A hint removes one wrong option and deducts 25 from a correct answer's award. Each round has three hints."))
            st.write(tr("A perfect round without hints adds 250 points × difficulty. Wrong and timed-out answers earn zero. You can always use Next to read the explanation at your own pace."))


def render_score_strip(quiz):
    html('<div class="score-strip">'
         f'<div class="score-item"><div class="score-label">Round score</div><div class="score-value">{quiz["score"]:,}</div></div>'
         f'<div class="score-item"><div class="score-label">Current streak</div><div class="score-value">{quiz["streak"]}</div></div>'
         f'<div class="score-item"><div class="score-label">Hints remaining</div><div class="score-value">{quiz["hints_remaining"]}</div></div></div>')


def render_active_round():
    quiz = st.session_state.quiz
    if not quiz or quiz["finished"] or st.session_state.show_setup or st.session_state.page != "Quiz":
        return
    ensure_question_clock(quiz)
    limit = question_time_limit(quiz)
    if not quiz["resolved"] and limit is not None and question_elapsed(quiz) >= limit:
        resolve_answer(None, quiz["serial"], quiz["index"])
    q = quiz["questions"][quiz["index"]]
    index, serial = quiz["index"], quiz["serial"]
    render_score_strip(quiz)
    st.caption(tr(f"Question {index + 1} of {len(quiz['questions'])} · {q['kind']} · {quiz['settings']['difficulty']}"))
    st.progress((index + int(quiz["resolved"])) / len(quiz["questions"]))
    with st.container(key="question_card"):
        if limit is not None:
            remaining = max(0, math.ceil(limit - question_elapsed(quiz))) if not quiz["resolved"] else 0
            st.caption(tr(f"Time remaining: {remaining} seconds" if not quiz["resolved"] else "Answer recorded"))
            if not quiz["resolved"]:
                st.progress(remaining / limit)
        st.subheader(tr(localized_question(q)))
        for offset in range(0, len(q["choices"]), 2):
            for column, choice in zip(st.columns(2), q["choices"][offset:offset + 2]):
                pos = q["choices"].index(choice)
                with column:
                    state, label = "neutral_answer", tr(choice)
                    if quiz["resolved"] and choice == q["answer"]:
                        state, label = "correct_answer", f"✓ {tr(choice)} — {tr('Correct answer')}"
                    elif quiz["resolved"] and choice == quiz["selected"]:
                        state, label = "wrong_answer", f"✕ {tr(choice)} — {tr('Your answer')}"
                    elif choice in quiz["hidden_options"]:
                        label = "Removed by hint"
                    with st.container(key=f"{state}_{pos}"):
                        st.button(tr(label), key=f"answer_{serial}_{index}_{pos}", use_container_width=True,
                                  disabled=quiz["resolved"] or choice in quiz["hidden_options"],
                                  on_click=resolve_answer, args=(choice, serial, index))
        if not quiz["resolved"] and len(q["choices"]) == 4:
            st.button(tr("Use hint · −25 if correct"), key=f"hint_{serial}_{index}",
                      disabled=quiz["hint_used"] or quiz["hints_remaining"] == 0,
                      on_click=use_hint, args=(serial, index))
        if quiz["resolved"]:
            recorded = quiz["history"][-1]
            if recorded["correct"]:
                st.success(tr(f"{tr('Correct!')} {tr(q['explanation'])}"))
            elif recorded["timed_out"]:
                st.warning(tr(f"{tr('Time is up.')} {tr('Correct answer')}: {tr(q['answer'])}. {tr(q['explanation'])}"))
            else:
                st.error(tr(f"{tr('Correct answer')}: {tr(q['answer'])}. {tr(q['explanation'])}"))
            award = quiz["last_points"]
            st.caption(tr(f"+{award['total']} points · Base {award['base']} · Speed +{award['speed']} · "
                       f"Streak +{award['streak']} · Hint −{award['hint']}"))
            final = index + 1 == len(quiz["questions"])
            with st.container(key="quiz_next_action"):
                if st.button(tr("View results" if final else "Next question →"), type="primary",
                             use_container_width=True, key=f"next_{serial}_{index}"):
                    advance_question(serial, index)
                    if quiz["finished"]:
                        st.rerun()
                    else:
                        st.rerun()


def render_answer_review(quiz):
    st.subheader(tr("Answer review"))
    for i, record in enumerate(quiz["history"], 1):
        q = record["question"]
        mark = "Correct" if record["correct"] else "Timed out" if record["timed_out"] else "Incorrect"
        with st.expander(tr(f"{i}. {mark} · {localized_question(q)}")):
            st.write(tr(f"Your answer: **{record['answer'] or 'Unanswered'}**"))
            st.write(tr(f"Correct answer: **{tr(q['answer'])}**"))
            st.write(tr(q["explanation"]))
            st.caption(tr(f"{record['elapsed']:.1f} seconds · {record['points']['total']} points · "
                       f"{'Hint used' if record['hint'] else 'No hint'}"))
            country = get_country(q["country_id"])
            st.caption(tr(f"{country['name']} · {country['continent']} · {country['region']}"))
            st.markdown(f"[Source]({q['source']})")
            if q.get("extra_source"):
                st.markdown(f"[Capital-role source]({q['extra_source']})")


def render_quiz_results(quiz):
    stats = quiz_statistics(quiz)
    with st.container(key="result_card"):
        html('<div class="eyebrow">Challenge complete</div>')
        st.subheader(tr("Your results"))
        html(f'<div class="result-number">{stats["score"]:,}<span class="result-unit"> points</span></div>')
        first, second, third = st.columns(3)
        first.metric(tr("Accuracy"), f"{stats['accuracy']:.0f}%")
        second.metric(tr("Correct answers"), f"{stats['correct']} / {stats['total']}")
        third.metric(tr("Best streak"), stats["best_streak"])
        st.caption(tr(f"Incorrect / unanswered: {stats['incorrect']} · Timed out: {stats['unanswered']} · "
                   f"Average response time: {stats['average_time']:.1f} seconds"))
        settings = quiz["settings"]
        country = get_country(settings["country_id"])
        st.caption(tr(f"{settings['continent']} · {country['name'] if country else 'All Countries'} · "
                   f"{settings['category']} · {settings['difficulty']} · {stats['total']} questions"))
        if quiz["perfect_bonus"]:
            st.success(tr(f"Perfect round without hints: +{quiz['perfect_bonus']} bonus points."))
        one, two = st.columns(2)
        with one:
            if st.button(tr("Play again"), type="primary", use_container_width=True):
                start_quiz(settings)
                st.rerun()
        with two:
            st.button(tr("Change settings"), use_container_width=True, on_click=open_setup)
        one, two = st.columns(2)
        with one:
            st.button(tr("Try another continent"), use_container_width=True, on_click=open_setup)
        with two:
            st.button(tr("Try another country"), use_container_width=True, on_click=open_setup)
        if st.button(tr("Review answers"), use_container_width=True):
            st.session_state.review_answers = not st.session_state.review_answers
    if st.session_state.review_answers:
        render_answer_review(quiz)


def render_quiz():
    quiz = st.session_state.quiz
    if not quiz or st.session_state.show_setup:
        intro, setup = st.columns([1, 1.15], gap="large")
        with intro:
            render_hero("The world geography challenge", "How well do you know your world?",
                        "Go beyond the familiar. Challenge yourself on capitals, currencies, languages and the places in between.", tall=True)
        with setup:
            render_quiz_setup()
        return
    render_hero("World Quiz", "Every answer takes you further.",
                "Think carefully. Build a streak. Discover something new.", compact=True)
    with st.container(key="settings_card"):
        summary, action = st.columns([3, 1])
        with summary:
            settings = quiz["settings"]
            country = get_country(settings["country_id"])
            label = country["name"] if country else settings["continent"]
            html('<div class="round-label">Current challenge</div>'
                 f'<div class="round-summary">{escape(label)} · {settings["difficulty"]} · {escape(settings["category"])}</div>')
        with action:
            st.button(tr("Change"), use_container_width=True, on_click=open_setup)
    if quiz["finished"]:
        render_quiz_results(quiz)
    else:
        interval = 1 if quiz["settings"]["timer"] else None
        st.fragment(run_every=interval)(render_active_round)()


def reset_explore_page():
    st.session_state.explore_page = 0


def change_explore_page(delta):
    st.session_state.explore_page = max(0, st.session_state.explore_page + delta)



# Curated photographs: actual locations, not generated scenery. Display crops only.
# Photos load directly in the browser; gradient artwork remains if a host is unavailable.
DESTINATION_PHOTOS = {
 'NGA': ('https://upload.wikimedia.org/wikipedia/commons/7/74/Lekki_Ikoyi_Link_Bridge.jpg', 'Lekki–Ikoyi Link Bridge, Lagos', 'Chippla', 'CC BY-SA 3.0', 'https://creativecommons.org/licenses/by-sa/3.0/', 'https://commons.wikimedia.org/wiki/File:Lekki_Ikoyi_Link_Bridge.jpg'),
 'JPN': ('https://upload.wikimedia.org/wikipedia/commons/9/9e/Chureito_Pagoda_and_Mount_Fuji.jpg', 'Chūrei-tō pagoda and Mount Fuji', 'Manishprabhune', 'CC BY-SA 4.0', 'https://creativecommons.org/licenses/by-sa/4.0/', 'https://commons.wikimedia.org/wiki/File:Chureito_Pagoda_and_Mount_Fuji.jpg'),
 'ITA': ('https://upload.wikimedia.org/wikipedia/commons/3/32/Colosseum_-_Rome.jpg', 'Colosseum, Rome', 'Mattia.masala', 'CC0', 'https://creativecommons.org/publicdomain/zero/1.0/', 'https://commons.wikimedia.org/wiki/File:Colosseum_-_Rome.jpg'),
 'BRA': ('https://upload.wikimedia.org/wikipedia/commons/9/98/National_Congress_of_Brazil_in_Bras%C3%ADlia.jpg', 'National Congress, Brasília', 'Agência Brasil', 'CC BY 3.0 BR', 'https://creativecommons.org/licenses/by/3.0/br/', 'https://commons.wikimedia.org/wiki/File:National_Congress_of_Brazil_in_Bras%C3%ADlia.jpg'),
}
UI_TRANSLATIONS.update({
 'Featured destination': ['Reiseziel im Fokus', 'Destino destacado', '精选目的地'],
 'A world of discovery.': ['Eine Welt voller Entdeckungen.', 'Un mundo por descubrir.', '发现精彩世界。'],
 'Where will curiosity take you?': ['Wohin führt dich deine Neugier?', '¿Adónde te llevará la curiosidad?', '好奇心会带你去哪里？'],
 'Explore places. Build knowledge. Find your next challenge.': ['Entdecke Orte. Erweitere dein Wissen. Finde deine nächste Herausforderung.', 'Explora lugares. Aprende. Encuentra tu próximo desafío.', '探索各地，积累知识，迎接下一场挑战。'],
 'Your next challenge': ['Deine nächste Herausforderung', 'Tu próximo desafío', '下一场挑战'],
 'Capitals, currencies, languages and more.': ['Hauptstädte, Währungen, Sprachen und mehr.', 'Capitales, monedas, idiomas y más.', '首都、货币、语言及更多知识。'],
 'Take a quiz →': ['Quiz starten →', 'Hacer un cuestionario →', '开始测验 →'],
 'Explore at your pace.': ['Entdecke in deinem Tempo.', 'Explora a tu ritmo.', '按自己的节奏探索。'],
 'Photography credits': ['Bildnachweise', 'Créditos fotográficos', '摄影署名'],
 'Discover →': ['Entdecken →', 'Descubrir →', '探索 →'],
 'Capital': ['Hauptstadt', 'Capital', '首都'],
 'Your discovery atlas': ['Dein Entdeckungsatlas', 'Tu atlas de descubrimientos', '你的探索图集'],
 'Photography loads online. Country illustrations are used where no curated photograph is included.': ['Fotos werden online geladen. Für andere Länder werden Illustrationen angezeigt.', 'Las fotos se cargan en línea. Se usan ilustraciones para los demás países.', '照片在线加载，未收录精选照片的国家使用插图。'],
})

st.markdown("""<style>
.stApp { background:radial-gradient(ellipse at 0% 0%,#e8f1ed,transparent 45%),#faf8f3; }
.brand-name { letter-spacing:-.035em; }.brand-symbol { border:1px solid #e4b65c55; }
.st-key-navigation { background:transparent !important; }
.st-key-navigation button[kind="primary"] { background:#102d40 !important;box-shadow:inset 0 -3px #e4b65c !important; }
.st-key-atlas_feature { position:relative;overflow:hidden;background:#102d40;border-radius:24px;padding:0 34px 28px !important;box-shadow:0 18px 42px #102d4020; }
.feature-scene { position:absolute;inset:0;background-color:#123f4a;background-size:cover;background-position:center 52%;pointer-events:none; }
.feature-scene::after { content:"";position:absolute;inset:0;background:linear-gradient(90deg,#071e2ff2 0%,#071e2fba 42%,#071e2f22 100%); }
.feature-copy { position:relative;z-index:1;max-width:640px;padding-top:34px; }
.feature-kicker { color:#f2cb7f;font-size:.73rem;letter-spacing:.18em;text-transform:uppercase;font-weight:700;margin-bottom:16px; }
.feature-title { color:#fff;font-size:clamp(2.1rem,4.2vw,3.4rem);font-weight:750;line-height:1.08;letter-spacing:-.045em;margin-bottom:16px; }
.feature-description { color:#e0e9ec;line-height:1.6;font-size:1rem;max-width:440px; }
.feature-place { color:#e5d0a8;font-size:.72rem;margin:15px 0 5px; }
.st-key-atlas_feature .stButton { position:relative;z-index:2;max-width:240px; }
.st-key-atlas_feature button[kind="primary"] { background:#008c91 !important; }
.atlas-heading { font-size:clamp(1.6rem,2.7vw,2.25rem);font-weight:750;color:#102d40;letter-spacing:-.04em;line-height:1.15;margin:15px 0 6px; }
.atlas-note { color:#536978;font-size:.9rem; }
[class*="st-key-country_card_"] { padding:0 0 15px !important;border-radius:16px !important;overflow:hidden;box-shadow:0 5px 20px #102d4009;transition:box-shadow .2s,transform .2s; }
[class*="st-key-country_card_"]:hover { transform:translateY(-3px);box-shadow:0 12px 28px #102d4017; }
.destination-cover { height:118px;background-color:#164b58;background-size:cover;background-position:center;position:relative;overflow:hidden; }
.destination-cover::after { content:"";position:absolute;inset:0;background:linear-gradient(0deg,#102d4055,transparent 70%); }
.destination-cover .destination-id { position:absolute;bottom:10px;left:14px;background:#102d40bf;border:1px solid #ffffff40;color:#fff;letter-spacing:.13em;font-size:.65rem;border-radius:20px;padding:4px 8px;z-index:1; }
.destination-cover svg { position:absolute;right:0;top:-35px;width:180px;height:180px;opacity:.6; }
.destination-copy { padding:0 15px; }
.destination-name { color:#102d40;font-size:1.13rem;font-weight:750;line-height:1.25;margin-top:7px; }
.destination-capital { color:#4b6474;font-size:.82rem;margin-top:4px;min-height:20px; }
.destination-region { color:#14767b;text-transform:uppercase;letter-spacing:.08em;font-size:.63rem;margin-top:9px;font-weight:700; }
[class*="st-key-country_card_"] .stButton { padding:0 15px; }
[class*="st-key-country_card_"] .stButton button { border:0 !important;background:transparent !important;color:#087e83 !important;min-height:32px;justify-content:flex-start;box-shadow:none !important; }
.st-key-atlas_quiz { background:radial-gradient(ellipse at top right,#196474,#102d40 65%);border-radius:20px;padding:28px !important;box-shadow:0 12px 25px #102d4014; }
.challenge-compass { color:#eac679;font-size:4.4rem;line-height:1;text-align:right;font-family:Georgia,serif; }
.challenge-title { color:white;font-size:1.8rem;line-height:1.15;font-weight:750;letter-spacing:-.035em;margin:18px 0 12px; }
.challenge-note { color:#dbe8ed;font-size:.95rem;line-height:1.65; }
.st-key-atlas_quiz button[kind="primary"] { background:#008c91 !important; }
.atlas-small { color:#71808a;font-size:.78rem;margin:12px 0;line-height:1.65; }
[data-testid="stDialog"] [role="dialog"] { background:#faf8f3 !important;box-shadow:10px 0 35px #102d4030 !important; }
[data-testid="stDialog"] button[kind="primary"] { background:#087e83 !important;border:0 !important; }
@media(max-width:850px) { .feature-title { font-size:2.35rem; }.st-key-atlas_feature { padding:0 24px 24px !important; } }
@media(max-width:600px) { .feature-copy { padding-top:25px; }.feature-title { font-size:2rem; }.feature-scene::after { background:linear-gradient(90deg,#071e2fe8,#071e2f88); }.destination-cover { height:145px; }.st-key-atlas_quiz { padding:24px !important; } }
@media(prefers-reduced-motion:reduce) { [class*="st-key-country_card_"]:hover { transform:none; } }
</style>""", unsafe_allow_html=True)


def atlas_photo_style(country_id):
    photo = DESTINATION_PHOTOS.get(country_id)
    if photo:
        return f"background-image:url('{photo[0]}');"
    shades = {'Africa':'#23645c','Asia':'#48667e','Europe':'#606574','South America':'#27756b','North America':'#305d79','Oceania':'#288287'}
    shade = shades.get(get_country(country_id)['continent'], '#23645c')
    return f'background-image:radial-gradient(ellipse at 80% 10%,{shade},#102d40);'


def render_photography_credits():
    with st.expander(tr('Photography credits')):
        st.caption(tr('Photography loads online. Country illustrations are used where no curated photograph is included.'))
        for photo in DESTINATION_PHOTOS.values():
            st.markdown(f'[{photo[1]}]({photo[5]}) — {photo[2]} · [{photo[3]}]({photo[4]}). Displayed with a layout crop/overlay; originals remain unchanged.')


def atlas_quiz():
    navigate('Quiz')

def render_explore():
    available = scoped_countries()
    preferred = ['NGA', 'JPN', 'ITA', 'BRA']
    feature = next((c for code in preferred for c in available if c['id'] == code), available[0])
    with st.container(key="atlas_feature"):
        html(f'<div class="feature-scene" style="{atlas_photo_style(feature["id"])}"></div>'
             '<div class="feature-copy"><div class="feature-kicker">Featured destination</div>'
             f'<div class="feature-title">{escape(feature["name"])}.<br>{escape(tr("A world of discovery."))}</div>'
             '<div class="feature-description">Explore places. Build knowledge. Find your next challenge.</div>'
             f'<div class="feature-place">{escape(DESTINATION_PHOTOS[feature["id"]][1]) if feature["id"] in DESTINATION_PHOTOS else escape(tr(feature["continent"]))}</div></div>')
        st.button(tr("Discover country →"), key="featured_discover", type="primary",
                  use_container_width=True, on_click=learn_country, args=(feature["id"],))
    with st.container(key="explore_scope"):
        area, change = st.columns([4, 1], vertical_alignment="center")
        with area:
            html(f'<div class="browse-scope">{escape(scope_label())}</div>')
        with change:
            if st.button(tr("Change"), key="atlas_scope_change", use_container_width=True):
                st.session_state.settings_open = True
                st.rerun()
    collection, invitation = st.columns([2.35, 1], gap="large")
    with collection:
        query = st.text_input(tr("Search countries or capitals"), key="explore_search",
                              on_change=reset_explore_page)
        entries = list(available)
        if query.strip():
            needle = query.strip().casefold()
            entries = [c for c in entries if needle in c["name"].casefold() or
                       any(needle in v["name"].casefold() for v in c["capitals"])]
        else:
            priority = {code: i for i, code in enumerate(['JPN', 'ITA', 'BRA', 'NGA'])}
            entries.sort(key=lambda c: (priority.get(c['id'], 99), c['name']))
        if not entries:
            st.info(tr("No countries match your search."))
        else:
            page_size = 3
            pages = math.ceil(len(entries) / page_size)
            page = min(st.session_state.explore_page, pages - 1)
            st.session_state.explore_page = page
            batch = entries[page * page_size:(page + 1) * page_size]
            for offset in range(0, len(batch), 3):
                for column, c in zip(st.columns(3), batch[offset:offset + 3]):
                    with column:
                        with st.container(key=f"country_card_{c['id']}"):
                            artwork = '' if c['id'] in DESTINATION_PHOTOS else globe_art()
                            html(f'<div class="destination-cover" role="img" aria-label="{escape(c["name"])}" style="{atlas_photo_style(c["id"])}">'
                                 f'{artwork}<span class="destination-id">{c["id"]}</span></div>'
                                 f'<div class="destination-copy"><div class="destination-region">{escape(tr(c["continent"]))}</div>'
                                 f'<div class="destination-name">{escape(c["name"])}</div>'
                                 f'<div class="destination-capital">{escape(" · ".join(v["name"] for v in c["capitals"]))}</div></div>')
                            st.button(tr("Discover →"), key=f"discover_{c['id']}", use_container_width=True,
                                      on_click=learn_country, args=(c["id"],))
            with st.container(key="explore_pagination"):
                previous, status, following = st.columns([1, 2, 1], vertical_alignment="center")
                with previous:
                    st.button(tr("Previous"), key="explore_previous", disabled=page == 0,
                              use_container_width=True, on_click=change_explore_page, args=(-1,))
                with status:
                    st.caption(tr(f"Page {page + 1} of {pages} · {len(entries)} countries"))
                with following:
                    st.button(tr("Next"), key="explore_next", disabled=page + 1 >= pages,
                              use_container_width=True, on_click=change_explore_page, args=(1,))
    with invitation:
        with st.container(key="atlas_quiz"):
            html('<div class="feature-kicker">Your next adventure</div>'
                 '<div class="challenge-compass" aria-hidden="true">✧</div>'
                 '<div class="challenge-title">Your next challenge</div>'
                 '<div class="challenge-note">Capitals, currencies, languages and more.</div>')
            st.button(tr("Take a quiz →"), key="atlas_take_quiz", type="primary", use_container_width=True,
                      on_click=atlas_quiz)
        html('<div class="atlas-small">Explore at your pace.</div>')
    render_photography_credits()


def render_learn():
    render_hero("The country collection", "Get to know the world.",
                "Build your knowledge, one country at a time. The details make all the difference.")
    country_id = st.selectbox(tr("Choose a country"), [c["id"] for c in scoped_countries()],
                              format_func=lambda i: get_country(i)["name"], key="learn_country")
    c = get_country(country_id)
    with st.container(key="learn_card"):
        html(f'<div class="country-top"><span class="country-code">{c["id"]}</span>'
             f'<span class="country-region">{escape(c["region"])}</span></div>')
        st.subheader(tr(c["name"]))
        facts = [("Continent / region", f"{c['continent']} · {c['region']}"),
                 ("Capital roles", "; ".join(f"{x['name']} ({x['role']})" for x in c["capitals"])),
                 ("Currencies", ", ".join(f"{x['name']} ({x['code']})" for x in c["currencies"])),
                 ("Official languages in this collection", ", ".join(c["official_languages"]) or "Not included yet")]
        tiles = "".join(f'<div class="fact-tile"><div class="fact-label">{escape(label)}</div>'
                        f'<div class="fact-value">{escape(value)}</div></div>' for label, value in facts)
        html(f'<div class="fact-grid">{tiles}</div>')
        neighbours = [get_country(i)["name"] for i in c["borders"] if get_country(i)]
        if neighbours:
            st.write(tr("Neighbours in this collection: " + ", ".join(neighbours)))
        leader = load_political_records().get(c["id"])
        if leader:
            st.write(tr(f"Head of state: **{' / '.join(leader['names'])}** ({leader['title']})."))
            st.caption(tr(f"Political record verified {leader['verified_on']}."))
            st.markdown(f"[Political source]({leader['source']})")
        st.markdown(f"[Country data source]({c['source']})")
        if c.get("capital_source"):
            st.markdown(f"[Capital-role source]({c['capital_source']})")


def render_badges():
    render_hero("Your explorer passport", "Curiosity deserves recognition.",
                "Every right answer is a step forward. Collect milestones as your knowledge grows.")
    st.caption(tr(f"{st.session_state.points:,} lifetime session points · {st.session_state.rounds_finished} rounds completed"))
    awards = [("First Steps", st.session_state.points >= 10, "Answer your first question correctly."),
              ("Century", st.session_state.points >= 100, "Earn 100 points."),
              ("Round Finisher", st.session_state.rounds_finished >= 1, "Complete your first quiz round.")]
    columns = st.columns(3)
    for i, (name, earned, description) in enumerate(awards):
        with columns[i]:
            with st.container(key=f"award_card_{i}"):
                symbol = ["✦", "★", "✓"][i]
                html(f'<div class="award-medal {"" if earned else "locked"}">{symbol}</div>')
                st.subheader(tr(name))
                html(f'<span class="award-state {"earned" if earned else ""}">{"Earned" if earned else "In progress"}</span>')
                st.caption(tr(description))


def render_data_sources():
    with st.expander(tr("Data sources and coverage")):
        st.markdown("Country data adapted from [mledoze/countries](https://github.com/mledoze/countries), "
                    "licensed under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). "
                    "The adapted embedded country database is distributed under the same license.")
        st.write(tr("Language questions use the included official-language lists. Missing or uncertain entries are skipped. "
                 "Population questions are omitted because this version has no dated population dataset."))
        st.markdown("Landmark locations are adapted from the [UNESCO World Heritage List](https://data.unesco.org/explore/dataset/whc001/), checked 8 October 2026. Only sites within one country are used. Country areas, domains and calling codes use the embedded country dataset; areas follow that source’s definitions.")
        st.write(tr("Head-of-state coverage is limited to dated, sourced records. Records older than 30 days are excluded until verified again. "
                 "This offline version does not automatically fetch political updates."))



st.markdown("""<style>
/* Balance only the quiz introduction against the challenge setup panel. */
.hero.hero-tall { min-height:0;padding:30px 34px; }
.hero.hero-tall .hero-title { font-size:2.65rem; }
.hero.hero-tall .hero-kicker { margin-bottom:12px; }
.hero.hero-tall .hero-description { font-size:.95rem;line-height:1.55;margin-top:14px; }
.hero.hero-tall .hero-tags { margin-top:18px; }
.hero.hero-tall .hero-art { width:215px;margin:8px auto 0; }
@media(max-width:850px) { .hero.hero-tall { padding:25px; }.hero.hero-tall .hero-title { font-size:2.2rem; }.hero.hero-tall .hero-art { width:185px; } }
@media(max-width:600px) { .hero.hero-tall .hero-art { width:115px;margin:0; }.hero.hero-tall .hero-title { font-size:2rem; } }
</style>""", unsafe_allow_html=True)



st.markdown("""<style>
@media(max-width:700px) {
 .stApp .block-container { padding:.65rem .8rem 1.1rem !important; }
 .st-key-app_header [data-testid="stHorizontalBlock"]:has(.st-key-header_menu) { flex-wrap:wrap !important;gap:10px !important; }
 .st-key-app_header [data-testid="stColumn"]:has(.st-key-header_menu) { flex:0 0 44px !important;width:44px !important;min-width:44px !important;max-width:44px !important; }
 .st-key-app_header [data-testid="stColumn"]:has(.st-key-header_brand) { flex:1 1 calc(100% - 64px) !important;width:calc(100% - 64px) !important;min-width:0 !important; }
 .st-key-app_header [data-testid="stColumn"]:has(.st-key-navigation) { flex:0 0 100% !important;width:100% !important;min-width:0 !important; }
 .st-key-navigation [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important;gap:3px !important; }
 .st-key-navigation [data-testid="stColumn"] { flex:1 1 0 !important;width:25% !important;min-width:0 !important; }
 .brand { min-height:44px;gap:9px; }.brand-symbol { width:38px;height:38px;border-radius:12px;flex-shrink:0; }
 .brand-symbol svg { width:24px;height:24px; }.brand-name { font-size:1.2rem; }.brand-note { display:none; }
 .st-key-navigation button { min-height:42px; }.st-key-navigation button p { font-size:.8rem !important; }
 .st-key-header_menu button { min-height:44px; }
 .stApp hr { margin:.4rem 0 .65rem !important; }
 .profile-note { font-size:.75rem;overflow-wrap:anywhere; }
 .stApp [data-testid="stVerticalBlock"] { gap:.65rem; }
 .hero { padding:18px !important;min-height:0 !important;border-radius:18px;gap:10px; }
 .hero-title,.hero.hero-tall .hero-title { font-size:1.7rem !important;line-height:1.12; }
 .hero-kicker { font-size:.63rem;margin-bottom:8px !important; }
 .hero-description { font-size:.86rem !important;line-height:1.45;margin-top:8px !important; }
 .hero-tags { margin-top:10px !important;gap:5px; }.hero-tags span { font-size:.65rem;padding:4px 7px; }
 .hero.hero-tall .hero-art { display:none; }
 .hero-compact { padding:14px 18px !important; }.hero-compact .hero-description { display:none; }
 .st-key-view_quiz:has(.st-key-question_card) .hero-compact { display:none; }
 .st-key-view_quiz:has(.st-key-result_card) .hero-compact { display:none; }
 .st-key-view_quiz .st-key-settings_card { padding:12px 14px !important;border-radius:14px !important; }
 .st-key-view_quiz .st-key-settings_card [data-testid="stHorizontalBlock"]:has(.round-summary) { flex-wrap:nowrap !important;gap:8px; }
 .st-key-view_quiz .st-key-settings_card [data-testid="stColumn"]:has(.round-summary) { flex:1 1 0 !important;min-width:0 !important; }
 .st-key-view_quiz .st-key-settings_card [data-testid="stColumn"]:has(.stButton) { min-width:0; }
 .st-key-view_quiz .st-key-settings_card:has(.round-summary) [data-testid="stColumn"]:last-child { flex:0 0 86px !important;width:86px !important;min-width:86px !important; }
 .round-label { font-size:.6rem; }.round-summary { font-size:.87rem;line-height:1.35;overflow-wrap:anywhere; }
 .score-strip { grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:0 0 3px; }
 .score-item { padding:9px 10px;border-radius:11px; }.score-label { font-size:.56rem;letter-spacing:.03em;line-height:1.25; }
 .score-value { font-size:1.3rem;line-height:1.3; }
 .st-key-question_card { padding:15px !important;border-radius:16px !important; }
 .st-key-question_card h3 { font-size:1.15rem !important;line-height:1.4 !important;padding-top:0 !important;overflow-wrap:anywhere; }
 .st-key-question_card .stButton button { min-height:48px;padding:9px 12px; }
 .st-key-question_card button p { font-size:.88rem !important;line-height:1.35;white-space:normal;overflow-wrap:anywhere; }
 .st-key-question_card [data-testid="stAlert"] { padding:10px 12px; }
 .st-key-question_card [data-testid="stAlert"] p { font-size:.87rem !important;line-height:1.4; }
 .stApp [data-baseweb="select"] > div { min-height:44px; }
 @media(min-width:360px) {
  .st-key-view_quiz .st-key-settings_card:not(:has(.round-summary)) [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important;gap:10px; }
  .st-key-view_quiz .st-key-settings_card:not(:has(.round-summary)) [data-testid="stColumn"] { flex:1 1 0 !important;min-width:0 !important;width:50% !important; }
 }
 .st-key-atlas_feature { padding:0 18px 18px !important;border-radius:18px; }
 .feature-copy { padding-top:20px; }.feature-title { font-size:1.85rem; }.feature-description { font-size:.85rem;line-height:1.4; }
 .feature-kicker { font-size:.62rem;margin-bottom:10px; }.feature-place { font-size:.65rem;margin:9px 0 3px; }
 .st-key-atlas_quiz { padding:18px !important; }.challenge-compass { display:none; }.challenge-title { font-size:1.4rem;margin:6px 0; }.challenge-note { font-size:.87rem;line-height:1.4; }
 [class*="st-key-country_card_"] { padding:12px !important; }
 .destination-cover { float:left;width:90px;height:100px;border-radius:10px;margin-right:12px; }
 .destination-cover svg { width:140px;height:140px;top:-20px; }
 .destination-copy { margin-left:102px;padding:0;min-height:100px; }
 .destination-region { margin-top:3px;font-size:.6rem; }.destination-name { font-size:1.05rem; }.destination-capital { font-size:.8rem; }
 [class*="st-key-country_card_"] .stButton { padding:0 0 0 102px; }
 [class*="st-key-country_card_"] .stButton button { min-height:36px; }
 .fact-grid { grid-template-columns:1fr;gap:8px; }.fact-tile { padding:3px 12px; }.fact-value { font-size:1rem;margin-bottom:9px; }
 [data-testid="stDialog"] [role="dialog"] { width:min(380px,94vw) !important;border-radius:0 18px 18px 0 !important; }
}
</style>""", unsafe_allow_html=True)



st.markdown("""<style>
/* Phone refinements based on the 400px preview; desktop rules stay intact. */
@media(max-width:700px) {
 .st-key-explore_scope [data-testid="stHorizontalBlock"],
 .st-key-explore_pagination [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important;gap:8px !important; }
 .st-key-explore_scope [data-testid="stColumn"],
 .st-key-explore_pagination [data-testid="stColumn"] { min-width:0 !important; }
 .st-key-explore_scope [data-testid="stColumn"]:first-child { flex:1 1 0 !important; }
 .st-key-explore_scope [data-testid="stColumn"]:last-child { flex:0 0 96px !important;width:96px !important; }
 .st-key-explore_pagination [data-testid="stColumn"] { flex:1 1 0 !important;width:auto !important; }
 .st-key-explore_pagination [data-testid="stColumn"]:nth-child(2) { flex:1.2 1 0 !important; }
 .st-key-explore_pagination button p { font-size:.78rem !important; }
 .st-key-explore_pagination [data-testid="stCaptionContainer"] p { font-size:.68rem !important;line-height:1.3; }
 .st-key-atlas_feature { padding:0 16px 14px !important; }
 .feature-copy { padding-top:16px; }.feature-title { font-size:1.65rem; }
 .feature-description { display:none; }.feature-place { margin-top:8px; }
 .destination-cover { width:76px;height:76px;margin-right:10px; }
 .destination-copy { margin-left:86px;min-height:65px; }
 [class*="st-key-country_card_"] .stButton { padding-left:86px; }
 [class*="st-key-country_card_"] .stButton button { min-height:38px;padding:4px 8px; }
 .st-key-atlas_quiz { padding:14px 16px !important; }
 .st-key-atlas_quiz .feature-kicker,.st-key-atlas_quiz .challenge-note,.atlas-small { display:none; }
 .challenge-title { font-size:1.12rem;margin:0 0 7px; }
 .st-key-view_learn .hero,.st-key-view_badges .hero { padding:15px 18px !important; }
 .st-key-view_learn .hero-art,.st-key-view_badges .hero-art,
 .st-key-view_learn .hero-tags,.st-key-view_badges .hero-tags,
 .st-key-view_learn .hero-description,.st-key-view_badges .hero-description { display:none; }
 .st-key-view_learn .hero-title,.st-key-view_badges .hero-title { font-size:1.4rem !important; }
 .st-key-learn_card { padding:16px !important; }
 .country-top { margin-bottom:5px; }.country-code { width:36px;height:36px;border-radius:10px; }
 .country-region { font-size:.62rem;max-width:70%;text-align:right; }
 .st-key-learn_card h3 { padding:0 !important;font-size:1.25rem !important; }
 .fact-grid { gap:6px;margin:4px 0; }.fact-label { margin-top:6px;font-size:.63rem; }
 .fact-value { font-size:.94rem;margin:3px 0 7px; }.fact-tile { border-radius:10px; }
 [class*="st-key-award_card_"] { position:relative;padding:14px 16px !important;border-radius:16px !important; }
 [class*="st-key-award_card_"] [data-testid="stVerticalBlock"] { gap:5px; }
 [class*="st-key-award_card_"] [data-testid="stMarkdownContainer"]:has(.award-medal) { position:absolute;right:9px;top:7px; }
 .award-medal { width:40px;height:40px;font-size:1.3rem;margin:0;box-shadow:0 0 0 4px #f8f2e4; }
 [class*="st-key-award_card_"] h3 { padding:0 55px 0 0 !important;font-size:1.12rem !important; }
 .award-state { padding:3px 9px;font-size:.7rem; }
 [class*="st-key-award_card_"] [data-testid="stCaptionContainer"] p { font-size:.8rem !important; }
}
</style>""", unsafe_allow_html=True)


st.markdown("""<style>
@media(max-width:700px) {
 /* Keep the round action reachable even with a long question or explanation. */
 .st-key-quiz_next_action { position:fixed !important;bottom:0;left:0;right:0;z-index:100;
  padding:10px 16px calc(10px + env(safe-area-inset-bottom,0px));
  background:#ffffffed;backdrop-filter:blur(12px);border-top:1px solid #c7dddf;
  box-shadow:0 -5px 20px #12394a14;margin:0 !important; }
 .st-key-quiz_next_action button[kind="primary"] { min-height:48px;background:#087e83 !important;
  border:1px solid #076a70 !important;box-shadow:0 3px 10px #087e8320; }
 .stApp .block-container:has(.st-key-quiz_next_action) { padding-bottom:calc(94px + env(safe-area-inset-bottom,0px)) !important; }
 .st-key-question_card:has(.st-key-quiz_next_action) { padding-bottom:14px !important; }
 .st-key-view_quiz .hero.hero-tall { padding:14px 18px !important; }
 .st-key-view_quiz .hero.hero-tall .hero-title { font-size:1.35rem !important; }
 .st-key-view_quiz .hero.hero-tall .hero-description,
 .st-key-view_quiz .hero.hero-tall .hero-tags { display:none; }
 .st-key-view_quiz [data-testid="stHorizontalBlock"]:has(.hero-tall) { row-gap:12px !important; }
 .st-key-view_quiz .st-key-settings_card h3 { font-size:1.2rem !important;padding-top:0 !important; }
 .st-key-view_quiz .st-key-settings_card .eyebrow { display:none; }
 .st-key-view_quiz [data-testid="stToggle"] label p { font-size:.75rem !important; }
 .st-key-view_quiz [data-testid="stToggle"] { margin-top:5px; }
 .st-key-view_quiz button[kind="primary"] { background:#087e83 !important;border-color:#076a70 !important; }
 .st-key-question_card { border-top:3px solid #087e83 !important; }
 .st-key-question_card .stButton button { background:#edf5f7;border-color:#bfd4de;color:#193e52; }
 .st-key-question_card .stButton button:disabled { color:#193e52; }
 [class*="st-key-correct_answer_"] button:disabled { background:#daf1e5 !important;border:2px solid #268257 !important;color:#145c3b !important; }
 [class*="st-key-wrong_answer_"] button:disabled { background:#fbe6e2 !important;border:2px solid #b64136 !important;color:#8f2d24 !important; }
 .st-key-question_card [data-testid="stAlert"] p { color:#253e4c !important; }
 .score-item:nth-child(2) { background:#fff0c9;border-color:#dec77d; }
 .score-item:nth-child(3) { background:#d9eeeb;border-color:#a8d1ca; }
 .st-key-question_card [data-testid="stVerticalBlock"] { gap:8px; }
}
</style>""", unsafe_allow_html=True)


st.markdown("""<style>
.profile-note { display:flex;align-items:center;gap:8px;margin:4px 0; }
.header-avatar { width:30px;height:30px;object-fit:cover;border-radius:50%;border:2px solid #c3deda;flex-shrink:0; }
.default-avatar { display:grid;place-items:center;background:#dfefec;color:#527d84;font-size:18px; }
.profile-preview { width:76px;height:76px;object-fit:cover;border-radius:50%;border:3px solid #d2e8e3; }
@media(max-width:700px) { .header-avatar { width:26px;height:26px; }.profile-note { font-size:.72rem; } }
</style>""", unsafe_allow_html=True)

def main():
    initialise_state()
    restore_account_profile()
    apply_preferences()
    with st.container(key="app_header"):
        render_brand_and_navigation()
    pages = {"Quiz": render_quiz, "Explore": render_explore, "Learn": render_learn, "Badges": render_badges}
    with st.container(key="view_" + st.session_state.page.lower()):
        pages.get(st.session_state.page, render_quiz)()
    st.divider()
    save_account_profile()
    persistence = "Saved to your account" if account_identity() and st.session_state.get("account_loaded") and not st.session_state.get("profile_save_error") else "Progress lasts for this browser session"
    st.caption(f"{len(COUNTRIES)} {tr('countries')} · {tr(persistence)}.")



if __name__ == "__main__":
    main()
