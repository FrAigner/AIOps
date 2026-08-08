import React from 'react';
import { css } from '@emotion/css';
import { GrafanaTheme2 } from '@grafana/data';
import { PluginPage } from '@grafana/runtime';
import { useStyles2 } from '@grafana/ui';
import ChatPanel from '../components/ChatPanel/ChatPanel';

function AssistantPage() {
  const s = useStyles2(getStyles);
  return (
    <PluginPage>
      <div className={s.wrapper}>
        <ChatPanel layout="wide" />
      </div>
    </PluginPage>
  );
}

export default AssistantPage;

const getStyles = (theme: GrafanaTheme2) => ({
  wrapper: css`
    height: calc(100vh - 200px);
  `,
});
