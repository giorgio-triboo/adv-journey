# Frontend Directory

Questa directory contiene tutti i file frontend del progetto.

## 📁 Struttura

```
frontend/
├── static/          # File statici (CSS, JS, immagini)
│   ├── css/
│   ├── js/
│   └── img/
│
└── templates/        # Template Jinja2 per rendering server-side
    ├── base.html
    ├── login.html
    ├── dashboard.html
    └── settings_*.html
```

## 🔧 Configurazione

I file sono serviti da FastAPI:
- **Static files**: montati su `/static` (CSS, JS, immagini)
- **Templates**: renderizzati server-side con Jinja2

## 📝 Note

- I template usano Tailwind CSS per lo styling
- I file statici sono serviti direttamente da FastAPI
- In Docker, questa directory è montata in `/app/frontend`
