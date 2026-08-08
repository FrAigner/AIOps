"use strict";(self.webpackChunkaiops_aiopsassistant_app=self.webpackChunkaiops_aiopsassistant_app||[]).push([[640],{611(e,t,a){a.d(t,["b",0,{appConfig:{chatBackendUrl:"data-testid ac-chat-backend-url",submit:"data-testid ac-submit-form"},assistantPage:{container:"data-testid assistant-page-container",input:"data-testid assistant-page-input",send:"data-testid assistant-page-send"}}])},640(e,t,a){a.r(t);var n=a(959),s=a.n(n),r=a(89),i=a(781),o=a(531),l=a(7),c=a(611);function d(e,t,a,n,s,r,i){try{var o=e[r](i),l=o.value}catch(e){return void a(e)}o.done?t(l):Promise.resolve(l).then(n,s)}function u(e){return function(){var t=this,a=arguments;return new Promise(function(n,s){var r=e.apply(t,a);function i(e){d(r,n,s,i,o,"next",e)}function o(e){d(r,n,s,i,o,"throw",e)}i(void 0)})}}const p=["Systemzustand zusammenfassen","Warum ist checkout gerade langsam?","Baue mir ein Dashboard mit Fehlerrate und Latenz von store-api"];const m=function(){var e,t;const a=(0,l.useStyles2)(f),r=(0,i.usePluginContext)(),d=((null!==(e=null==r||null===(t=r.meta)||void 0===t?void 0:t.jsonData)&&void 0!==e?e:{}).chatBackendUrl||"http://localhost:8090").replace(/\/$/,""),[m,g]=(0,n.useState)([]),[h,y]=(0,n.useState)(""),[b,x]=(0,n.useState)("Wird bei der ersten Frage geladen."),[v,$]=(0,n.useState)(!1),[k,w]=(0,n.useState)(null),E=e=>u(function*(){const t=e.trim();if(!t||v)return;w(null),$(!0);const a=[...m,{role:"user",content:t}];g(a),y("");try{const{reply:e,context:n}=yield function(e,t,a){return u(function*(){const n=yield fetch(`${e}/chat`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:t,history:a})});if(!n.ok)throw new Error(`Backend antwortete mit ${n.status}`);return n.json()})()}(d,t,m);g([...a,{role:"assistant",content:e}]),x(n)}catch(e){w(`Chat-Backend (${d}) nicht erreichbar: ${e instanceof Error?e.message:String(e)}. Backend-URL laesst sich unter Configuration anpassen.`)}finally{$(!1)}})();return s().createElement(o.PluginPage,null,s().createElement("div",{className:a.layout,"data-testid":c.b.assistantPage.container},s().createElement("div",{className:a.chatColumn},k&&s().createElement(l.Alert,{severity:"warning",title:"Verbindungsproblem"},k),0===m.length&&s().createElement("div",{className:a.examples},p.map(e=>s().createElement(l.Button,{key:e,variant:"secondary",size:"sm",onClick:()=>E(e),disabled:v},e))),s().createElement("div",{className:a.messages},m.map((e,t)=>s().createElement("div",{key:t,className:"user"===e.role?a.userBubble:a.assistantBubble},e.content)),v&&s().createElement("div",{className:a.assistantBubble},s().createElement(l.Icon,{name:"fa fa-spinner",className:a.spinner})," denkt nach ...")),s().createElement("div",{className:a.inputRow},s().createElement(l.TextArea,{"data-testid":c.b.assistantPage.input,placeholder:"Frage stellen...",value:h,rows:2,onChange:e=>y(e.currentTarget.value),onKeyDown:e=>{"Enter"!==e.key||e.shiftKey||(e.preventDefault(),E(h))}}),s().createElement(l.Button,{"data-testid":c.b.assistantPage.send,onClick:()=>E(h),disabled:v},"Senden"))),s().createElement("div",{className:a.contextColumn},s().createElement("div",{className:a.contextTitle},"Verwendeter Kontext"),s().createElement("pre",{className:a.contextText},b))))},f=e=>({layout:r.css`
    display: flex;
    gap: ${e.spacing(2)};
    height: calc(100vh - 200px);
  `,chatColumn:r.css`
    flex: 2;
    display: flex;
    flex-direction: column;
    gap: ${e.spacing(1)};
    min-width: 0;
  `,contextColumn:r.css`
    flex: 1;
    background: ${e.colors.background.secondary};
    border-radius: ${e.shape.radius.default};
    padding: ${e.spacing(2)};
    overflow-y: auto;
  `,contextTitle:r.css`
    font-weight: ${e.typography.fontWeightMedium};
    text-transform: uppercase;
    font-size: ${e.typography.bodySmall.fontSize};
    color: ${e.colors.text.secondary};
    margin-bottom: ${e.spacing(1)};
  `,contextText:r.css`
    white-space: pre-wrap;
    font-size: ${e.typography.bodySmall.fontSize};
    font-family: ${e.typography.fontFamilyMonospace};
    color: ${e.colors.text.secondary};
  `,examples:r.css`
    display: flex;
    gap: ${e.spacing(1)};
    flex-wrap: wrap;
  `,messages:r.css`
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: ${e.spacing(1)};
  `,userBubble:r.css`
    align-self: flex-end;
    background: ${e.colors.primary.main};
    color: ${e.colors.primary.contrastText};
    padding: ${e.spacing(1,1.5)};
    border-radius: ${e.shape.radius.default};
    max-width: 80%;
  `,assistantBubble:r.css`
    align-self: flex-start;
    background: ${e.colors.background.secondary};
    padding: ${e.spacing(1,1.5)};
    border-radius: ${e.shape.radius.default};
    max-width: 80%;
  `,inputRow:r.css`
    display: flex;
    gap: ${e.spacing(1)};
    align-items: flex-end;
  `,spinner:r.css`
    animation: spin 1s linear infinite;
    @keyframes spin {
      from {
        transform: rotate(0deg);
      }
      to {
        transform: rotate(360deg);
      }
    }
  `});a.d(t,["default",0,m])}}]);
//# sourceMappingURL=640.js.map?_cache=5365896e2968def51ae1