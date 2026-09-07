"use client";

import { FormEvent, useEffect, useState } from "react";

import { SiteHeader } from "@/components/site-header";
import {
  deleteOpenAIKey,
  getOpenAIKeyStatus,
  saveOpenAIKey,
} from "@/lib/api";
import type { ApiKeyStatus } from "@/lib/types";

export default function SettingsPage() {
  const [status, setStatus] = useState<ApiKeyStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void getOpenAIKeyStatus()
      .then(setStatus)
      .catch((error) =>
        setMessage(error instanceof Error ? error.message : "Could not load settings"),
      )
      .finally(() => setLoading(false));
  }, []);

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      const nextStatus = await saveOpenAIKey(apiKey);
      setStatus(nextStatus);
      setApiKey("");
      setMessage("OpenAI key saved securely.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save the API key");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setSaving(true);
    setMessage(null);
    try {
      await deleteOpenAIKey();
      setStatus({ configured: false, last4: null });
      setMessage("OpenAI key removed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not remove the API key");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="account-page">
      <SiteHeader context="Settings" actionLabel="New project" />
      <main className="account-main settings-main">
        <div className="account-page-heading">
          <div>
            <h1>Settings</h1>
            <p>Manage the API key used to process your videos.</p>
          </div>
        </div>

        <section className="settings-card">
          <div className="settings-card-heading">
            <div>
              <h2>OpenAI API key</h2>
              <p>
                Your key pays OpenAI directly for transcription and analysis. ClipCraft encrypts
                it before storing it.
              </p>
            </div>
            {!loading && (
              <span className={status?.configured ? "key-status configured" : "key-status"}>
                {status?.configured ? `Configured ····${status.last4}` : "Not configured"}
              </span>
            )}
          </div>

          <form onSubmit={handleSave}>
            <label>
              {status?.configured ? "Replace API key" : "API key"}
              <input
                required
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="sk-..."
              />
            </label>
            <button type="submit" disabled={saving || loading}>
              {saving ? "Saving…" : status?.configured ? "Replace key" : "Save key"}
            </button>
          </form>

          <div className="settings-security">
            <strong>How it is protected</strong>
            <p>
              The key is encrypted with AES-256-GCM and can only be decrypted by the processing
              API. It is never returned to the browser after saving.
            </p>
          </div>

          {status?.configured && (
            <button
              className="remove-key-button"
              type="button"
              disabled={saving}
              onClick={handleDelete}
            >
              Remove saved key
            </button>
          )}
          {message && <p className="settings-message">{message}</p>}
        </section>
      </main>
    </div>
  );
}
