# Проверка разметки golden set

60 вопросов из test ДЗ3, не из train и не из val выбора кандидата. Группировка по стране сохранена: ни одна страна golden не встречается в train. Полный индекс содержит все исходные train-вопросы, а не только пул 32 короткого поиска.

Эталон каждой строки сверен с отдельной записью закреплённого geonamescache==3.0.2 и с исходным assistant-ответом собственного датасета. Население относится к этому снимку и не выдаётся за современную численность. Таблица позволяет проверить каждое соответствие вручную; независимая человеческая экспертиза не заявляется.

| ID | Город | Поле | Метка | Исходный факт | GeoNames ID |
|---|---|---|---|---|---|
| golden-geonames-v2-1816670-country | Beijing | country | A | China | 1816670 |
| golden-geonames-v2-1795565-country | Shenzhen | country | C | China | 1795565 |
| golden-geonames-v2-1809858-country | Guangzhou | country | B | China | 1809858 |
| golden-geonames-v2-745044-country | Istanbul | country | A | Turkey | 745044 |
| golden-geonames-v2-1815286-country | Chengdu | country | C | China | 1815286 |
| golden-geonames-v2-3688689-country | Bogotá | country | B | Colombia | 3688689 |
| golden-geonames-v2-112931-country | Tehran | country | A | Iran | 112931 |
| golden-geonames-v2-2147714-country | Sydney | country | C | Australia | 2147714 |
| golden-geonames-v2-2158177-country | Melbourne | country | B | Australia | 2158177 |
| golden-geonames-v2-323786-country | Ankara | country | A | Turkey | 323786 |
| golden-geonames-v2-750269-country | Bursa | country | C | Turkey | 750269 |
| golden-geonames-v2-311046-country | İzmir | country | B | Turkey | 311046 |
| golden-geonames-v2-2174003-country | Brisbane | country | A | Australia | 2174003 |
| golden-geonames-v2-53654-country | Mogadishu | country | C | Somalia | 53654 |
| golden-geonames-v2-3687925-country | Cali | country | B | Colombia | 3687925 |
| golden-geonames-v2-2063523-country | Perth | country | A | Australia | 2063523 |
| golden-geonames-v2-124665-country | Mashhad | country | C | Iran | 124665 |
| golden-geonames-v2-314830-country | Gaziantep | country | B | Turkey | 314830 |
| golden-geonames-v2-3674962-country | Medellín | country | A | Colombia | 3674962 |
| golden-geonames-v2-418863-country | Isfahan | country | C | Iran | 418863 |
| golden-geonames-v2-1796236-population | Shanghai | population | B | 24874500 | 1796236 |
| golden-geonames-v2-1816670-population | Beijing | population | A | 18960744 | 1816670 |
| golden-geonames-v2-1795565-population | Shenzhen | population | C | 17494398 | 1795565 |
| golden-geonames-v2-1809858-population | Guangzhou | population | B | 16096724 | 1809858 |
| golden-geonames-v2-745044-population | Istanbul | population | A | 15701602 | 745044 |
| golden-geonames-v2-1815286-population | Chengdu | population | C | 13568357 | 1815286 |
| golden-geonames-v2-3688689-population | Bogotá | population | B | 7674366 | 3688689 |
| golden-geonames-v2-112931-population | Tehran | population | A | 7153309 | 112931 |
| golden-geonames-v2-2147714-population | Sydney | population | C | 5638830 | 2147714 |
| golden-geonames-v2-2158177-population | Melbourne | population | B | 5435590 | 2158177 |
| golden-geonames-v2-323786-population | Ankara | population | A | 3517182 | 323786 |
| golden-geonames-v2-750269-population | Bursa | population | C | 3101833 | 750269 |
| golden-geonames-v2-311046-population | İzmir | population | B | 2938292 | 311046 |
| golden-geonames-v2-2174003-population | Brisbane | population | A | 2780063 | 2174003 |
| golden-geonames-v2-53654-population | Mogadishu | population | C | 2587183 | 53654 |
| golden-geonames-v2-3687925-population | Cali | population | B | 2392877 | 3687925 |
| golden-geonames-v2-2063523-population | Perth | population | A | 2384371 | 2063523 |
| golden-geonames-v2-124665-population | Mashhad | population | C | 2307177 | 124665 |
| golden-geonames-v2-314830-population | Gaziantep | population | B | 2222415 | 314830 |
| golden-geonames-v2-3674962-population | Medellín | population | A | 1999979 | 3674962 |
| golden-geonames-v2-1796236-timezone | Shanghai | timezone | C | Asia/Shanghai | 1796236 |
| golden-geonames-v2-1816670-timezone | Beijing | timezone | B | Asia/Shanghai | 1816670 |
| golden-geonames-v2-1795565-timezone | Shenzhen | timezone | A | Asia/Shanghai | 1795565 |
| golden-geonames-v2-1809858-timezone | Guangzhou | timezone | C | Asia/Shanghai | 1809858 |
| golden-geonames-v2-745044-timezone | Istanbul | timezone | B | Europe/Istanbul | 745044 |
| golden-geonames-v2-1815286-timezone | Chengdu | timezone | A | Asia/Shanghai | 1815286 |
| golden-geonames-v2-3688689-timezone | Bogotá | timezone | C | America/Bogota | 3688689 |
| golden-geonames-v2-112931-timezone | Tehran | timezone | B | Asia/Tehran | 112931 |
| golden-geonames-v2-2147714-timezone | Sydney | timezone | A | Australia/Sydney | 2147714 |
| golden-geonames-v2-2158177-timezone | Melbourne | timezone | C | Australia/Melbourne | 2158177 |
| golden-geonames-v2-323786-timezone | Ankara | timezone | B | Europe/Istanbul | 323786 |
| golden-geonames-v2-750269-timezone | Bursa | timezone | A | Europe/Istanbul | 750269 |
| golden-geonames-v2-311046-timezone | İzmir | timezone | C | Europe/Istanbul | 311046 |
| golden-geonames-v2-2174003-timezone | Brisbane | timezone | B | Australia/Brisbane | 2174003 |
| golden-geonames-v2-53654-timezone | Mogadishu | timezone | A | Africa/Mogadishu | 53654 |
| golden-geonames-v2-3687925-timezone | Cali | timezone | C | America/Bogota | 3687925 |
| golden-geonames-v2-2063523-timezone | Perth | timezone | B | Australia/Perth | 2063523 |
| golden-geonames-v2-124665-timezone | Mashhad | timezone | A | Asia/Tehran | 124665 |
| golden-geonames-v2-314830-timezone | Gaziantep | timezone | C | Europe/Istanbul | 314830 |
| golden-geonames-v2-3674962-timezone | Medellín | timezone | B | America/Bogota | 3674962 |

Координаты не включены: выбираются три однозначных факта. Слово «город» не устраняет все омонимы; поэтому источник фиксирует GeoNames ID. Точное сравнение строк и group_id не доказывает отсутствие всех смысловых утечек. Повторное использование test этого учебного проекта не является независимым аудитом.
