@echo off
cd /d C:\Users\anufr\PycharmProjects\oma_be
.venv\Scripts\python.exe -c "import json;from pathlib import Path;p=Path('backend/data/products/products.json');d=json.loads(p.read_text(encoding='utf-8'));print('products',len(d));print('ids', [x['id'] for x in d]);print('cats',sorted({x.get('category_id') for x in d}));imgs=list(Path('backend/data/images/products').rglob('*.*'));print('image_files',len(imgs));print('with_local',sum(1 for x in d if x.get('local_images')))"
