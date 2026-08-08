import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppRootProps } from '@grafana/data';
const AssistantPage = React.lazy(() => import('../../pages/AssistantPage'));

function App(_props: AppRootProps) {
  return (
    <Routes>
      <Route path="*" element={<AssistantPage />} />
    </Routes>
  );
}

export default App;
