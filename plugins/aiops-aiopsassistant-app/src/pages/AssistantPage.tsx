import React, { useState } from 'react';
import { css } from '@emotion/css';
import { GrafanaTheme2, usePluginContext } from '@grafana/data';
import { PluginPage } from '@grafana/runtime';
import { Button, Icon, TextArea, useStyles2, Alert } from '@grafana/ui';
import { testIds } from '../components/testIds';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};

type PluginJsonData = {
  chatBackendUrl?: string;
};

const DEFAULT_BACKEND_URL = 'http://localhost:8090';

const EXAMPLE_QUESTIONS = [
  'Systemzustand zusammenfassen',
  'Warum ist checkout gerade langsam?',
  'Baue mir ein Dashboard mit Fehlerrate und Latenz von store-api',
];

async function askAssistant(
  backendUrl: string,
  message: string,
  history: ChatMessage[]
): Promise<{ reply: string; context: string }> {
  const res = await fetch(`${backendUrl}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  });
  if (!res.ok) {
    throw new Error(`Backend antwortete mit ${res.status}`);
  }
  return res.json();
}

function AssistantPage() {
  const s = useStyles2(getStyles);
  const context = usePluginContext();
  const jsonData = (context?.meta?.jsonData ?? {}) as PluginJsonData;
  const backendUrl = (jsonData.chatBackendUrl || DEFAULT_BACKEND_URL).replace(/\/$/, '');

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [contextText, setContextText] = useState('Wird bei der ersten Frage geladen.');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || loading) {
      return;
    }
    setError(null);
    setLoading(true);
    const nextMessages = [...messages, { role: 'user' as const, content: question }];
    setMessages(nextMessages);
    setInput('');
    try {
      const { reply, context: newContext } = await askAssistant(backendUrl, question, messages);
      setMessages([...nextMessages, { role: 'assistant', content: reply }]);
      setContextText(newContext);
    } catch (e) {
      setError(
        `Chat-Backend (${backendUrl}) nicht erreichbar: ${e instanceof Error ? e.message : String(e)}. ` +
          'Backend-URL laesst sich unter Configuration anpassen.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <PluginPage>
      <div className={s.layout} data-testid={testIds.assistantPage.container}>
        <div className={s.chatColumn}>
          {error && (
            <Alert severity="warning" title="Verbindungsproblem">
              {error}
            </Alert>
          )}

          {messages.length === 0 && (
            <div className={s.examples}>
              {EXAMPLE_QUESTIONS.map((q) => (
                <Button key={q} variant="secondary" size="sm" onClick={() => send(q)} disabled={loading}>
                  {q}
                </Button>
              ))}
            </div>
          )}

          <div className={s.messages}>
            {messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? s.userBubble : s.assistantBubble}>
                {m.content}
              </div>
            ))}
            {loading && (
              <div className={s.assistantBubble}>
                <Icon name="fa fa-spinner" className={s.spinner} /> denkt nach ...
              </div>
            )}
          </div>

          <div className={s.inputRow}>
            <TextArea
              data-testid={testIds.assistantPage.input}
              placeholder="Frage stellen..."
              value={input}
              rows={2}
              onChange={(e) => setInput(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
            />
            <Button data-testid={testIds.assistantPage.send} onClick={() => send(input)} disabled={loading}>
              Senden
            </Button>
          </div>
        </div>

        <div className={s.contextColumn}>
          <div className={s.contextTitle}>Verwendeter Kontext</div>
          <pre className={s.contextText}>{contextText}</pre>
        </div>
      </div>
    </PluginPage>
  );
}

export default AssistantPage;

const getStyles = (theme: GrafanaTheme2) => ({
  layout: css`
    display: flex;
    gap: ${theme.spacing(2)};
    height: calc(100vh - 200px);
  `,
  chatColumn: css`
    flex: 2;
    display: flex;
    flex-direction: column;
    gap: ${theme.spacing(1)};
    min-width: 0;
  `,
  contextColumn: css`
    flex: 1;
    background: ${theme.colors.background.secondary};
    border-radius: ${theme.shape.radius.default};
    padding: ${theme.spacing(2)};
    overflow-y: auto;
  `,
  contextTitle: css`
    font-weight: ${theme.typography.fontWeightMedium};
    text-transform: uppercase;
    font-size: ${theme.typography.bodySmall.fontSize};
    color: ${theme.colors.text.secondary};
    margin-bottom: ${theme.spacing(1)};
  `,
  contextText: css`
    white-space: pre-wrap;
    font-size: ${theme.typography.bodySmall.fontSize};
    font-family: ${theme.typography.fontFamilyMonospace};
    color: ${theme.colors.text.secondary};
  `,
  examples: css`
    display: flex;
    gap: ${theme.spacing(1)};
    flex-wrap: wrap;
  `,
  messages: css`
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: ${theme.spacing(1)};
  `,
  userBubble: css`
    align-self: flex-end;
    background: ${theme.colors.primary.main};
    color: ${theme.colors.primary.contrastText};
    padding: ${theme.spacing(1, 1.5)};
    border-radius: ${theme.shape.radius.default};
    max-width: 80%;
  `,
  assistantBubble: css`
    align-self: flex-start;
    background: ${theme.colors.background.secondary};
    padding: ${theme.spacing(1, 1.5)};
    border-radius: ${theme.shape.radius.default};
    max-width: 80%;
  `,
  inputRow: css`
    display: flex;
    gap: ${theme.spacing(1)};
    align-items: flex-end;
  `,
  spinner: css`
    animation: spin 1s linear infinite;
    @keyframes spin {
      from {
        transform: rotate(0deg);
      }
      to {
        transform: rotate(360deg);
      }
    }
  `,
});
