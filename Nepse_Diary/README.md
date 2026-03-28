# Fast_API
Markdown
# 📈 NEPSE Analyst Terminal - Cloud API

A high-performance, read-only analytical backend designed to process and serve Nepal Stock Exchange (NEPSE) portfolio data. Built with **FastAPI**, **Pandas**, and **Neon PostgreSQL**, this API acts as the secure data engine for the NEPSE Analyst Terminal.

## 🏗️ Architecture Overview

This project utilizes a **True Monorepo Architecture**. The master repository is designed to house multiple isolated backend services in the future. Currently, it hosts the `Nepse_Diary` application.

* **Heavy-Lifting Backend:** Instead of sending massive raw database tables to the client, this API uses Python (Pandas) to perform complex financial calculations (FIFO WACC, partial sells, live P&L) server-side. This results in lightning-fast response times and minimal data payloads for mobile clients.
* **Modular Routing:** The API is split into distinct logical routers (`raw_tables` and `active_portfolio`) to maintain clean, scalable code.
* **Serverless Database:** Connected directly to a Neon serverless PostgreSQL database using SQLAlchemy.

## 📂 Directory Structure

```text
/Fast_API_Repo                  # Master Monorepo Root
└── /Nepse_Diary                # Target Application Folder
    ├── Nepse_Diary_Read_Only_Backend.py  # Main FastAPI Gateway
    ├── database.py             # SQLAlchemy Engine & Neon Connection
    ├── raw_tables.py           # APIRouter for 8 standard DB tables
    ├── active_portfolio.py     # APIRouter for complex P&L calculations
    └── requirements.txt        # Python dependencies
🛠️ Core Tech Stack
Framework: FastAPI (Python)

Data Processing: Pandas, NumPy

Database Interface: SQLAlchemy, psycopg2-binary

Database: Neon PostgreSQL

Deployment: Render (Cloud Native)

📡 API Endpoints
All endpoints are strictly Read-Only (GET) and return formatted JSON payloads.

1. Analytics Endpoints
GET /api/active_portfolio

Description: The powerhouse of the API. Fetches raw transaction history, applies NEPSE-standard FIFO logic to calculate partial sells and accurate WACC, merges live LTP from the cache table, and calculates Live P&L, Breakeven points, and Portfolio Weightage. Includes a summarized metadata object.

2. Raw Data Endpoints (Mirroring DB Tables)
GET /api/portfolio - Raw buy/sell ledger

GET /api/cache - Live scraped market prices (LTP)

GET /api/watchlist - Target stock tracking

GET /api/wealth - Net worth snapshot history

GET /api/audit_log - System logs

GET /api/history - Trade history

GET /api/tms_trx - Raw TMS transaction data

GET /api/trading_journal - Analyst notes and trade setups

🔒 Security Features
Strict CORS Policy: The API rejects requests from unauthorized origins. It only accepts GET requests from the explicitly defined frontend URL.

Invisible API (Docs Disabled): Swagger UI (/docs) and ReDoc (/redoc) are intentionally disabled in production to hide the database schema from web scrapers and unauthorized users.

Read-Only Enforcement: The FastAPI endpoints are hardcoded to only execute SELECT SQL queries. No POST, PUT, or DELETE routes exist.

Environment Variables: Database credentials are never hardcoded. They are injected securely at runtime via the DATABASE_URL environment variable.

🚀 Deployment Guide (Render)
This application is optimized for Render's Free Web Service Tier. Because of the Monorepo structure, specific settings must be applied during deployment.

Render Configuration
Environment: Python 3

Root Directory: Nepse_Diary (Crucial: Tells Render to ignore the repo root)

Build Command: pip install -r requirements.txt

Start Command: uvicorn Nepse_Diary_Read_Only_Backend:app --host 0.0.0.0 --port $PORT

Required Environment Variables
DATABASE_URL: Your Neon PostgreSQL connection string.
(Note: The API automatically handles replacing postgres:// with the required postgresql+psycopg2:// driver prefix).

⚡ The "Keep-Alive" Strategy (Cold Start Mitigation)
Render's free tier spins down the server after 15 minutes of inactivity, resulting in a ~50-second "Cold Start" delay on the next request.

To ensure the terminal dashboard loads instantly 24/7, this API is paired with a free cron job service (e.g., cron-job.org).

Target: https://<your-render-url>.onrender.com/

Interval: Every 14 minutes.

Result: Bypasses sleep mode while remaining safely within Render's 750 free monthly compute hours.

Built for precision. Deployed for speed.
