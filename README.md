Voice + Text AI Booking Agent

A system that lets users book calls or AI agents through text or voice. The assistant extracts booking details, confirms them, sends WhatsApp updates, and can generate a UPI QR for payments. It handles interruptions, slang, and small talk without losing the booking flow. It also sends confirmation messages through whatsapp api (twilio)

Features

Text and voice input (voice → text via Speech Recognition)

Auto-detected phone number from Twilio with country code confirmation

Intent, date, time, and detail extraction

Booking proposals with pricing and unique booking IDs

WhatsApp confirmations, catalogs, locations, and QR payment links

Natural tone adjustments and safe handling of unrelated questions

Automatically fetches phone number through URL when user comes to webpage through twilio sandbox

Architecture

Frontend: Simple HTML/JS interface for typing or recording audio; phone passed from Twilio.
Backend: Flask server with /api/text and /api/voice. Audio is converted and transcribed locally.
Orchestration: Rule-based slot filling + low-temperature LLM for intent and rewriting. Validates outputs to prevent hallucination and maintains a controlled booking workflow.
Tools: Modules for phone handling, date validation, QR creation, WhatsApp messaging, and booking storage.

Stack

Python, Flask, Whisper (local), Gemini Flash Lite, Twilio WhatsApp API, SQLite.

Summary

A compact, end-to-end assistant combining voice, text, LLM reasoning, and real messaging APIs to create a practical booking experience
