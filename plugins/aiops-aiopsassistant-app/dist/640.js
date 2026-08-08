"use strict";(self.webpackChunkaiops_aiopsassistant_app=self.webpackChunkaiops_aiopsassistant_app||[]).push([[640],{278(e,t,a){var n=a(959),s=a.n(n),r=a(89),i=a(781),o=a(7),l=a(611);function c(e,t,a,n,s,r,i){try{var o=e[r](i),l=o.value}catch(e){return void a(e)}o.done?t(l):Promise.resolve(l).then(n,s)}function d(e){return function(){var t=this,a=arguments;return new Promise(function(n,s){var r=e.apply(t,a);function i(e){c(r,n,s,i,o,"next",e)}function o(e){c(r,n,s,i,o,"throw",e)}i(void 0)})}}const u=["Systemzustand zusammenfassen","Warum ist checkout gerade langsam?","Baue mir ein Dashboard mit Fehlerrate und Latenz von store-api"];const p=function({layout:e="wide"}){var t,a;const c=(0,o.useStyles2)(m),p=(0,i.usePluginContext)(),g=((null!==(t=null==p||null===(a=p.meta)||void 0===a?void 0:a.jsonData)&&void 0!==t?t:{}).chatBackendUrl||"http://localhost:8090").replace(/\/$/,""),[f,h]=(0,n.useState)([]),[y,x]=(0,n.useState)(""),[b,v]=(0,n.useState)("Wird bei der ersten Frage geladen."),[w,$]=(0,n.useState)(!1),[k,E]=(0,n.useState)(null),S=e=>d(function*(){const t=e.trim();if(!t||w)return;E(null),$(!0);const a=[...f,{role:"user",content:t}];h(a),x("");try{const{reply:e,context:n}=yield function(e,t,a){return d(function*(){const n=yield fetch(`${e}/chat`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message:t,history:a})});if(!n.ok)throw new Error(`Backend antwortete mit ${n.status}`);return n.json()})()}(g,t,f);h([...a,{role:"assistant",content:e}]),v(n)}catch(e){E(`Chat-Backend (${g}) nicht erreichbar: ${e instanceof Error?e.message:String(e)}. Backend-URL laesst sich unter Configuration anpassen.`)}finally{$(!1)}})();return s().createElement("div",{className:(0,r.cx)(c.layout,"narrow"===e&&c.layoutNarrow),"data-testid":l.b.assistantPage.container},s().createElement("div",{className:c.chatColumn},k&&s().createElement(o.Alert,{severity:"warning",title:"Verbindungsproblem"},k),0===f.length&&s().createElement("div",{className:c.examples},u.map(e=>s().createElement(o.Button,{key:e,variant:"secondary",size:"sm",onClick:()=>S(e),disabled:w},e))),s().createElement("div",{className:c.messages},f.map((e,t)=>s().createElement("div",{key:t,className:"user"===e.role?c.userBubble:c.assistantBubble},e.content)),w&&s().createElement("div",{className:c.assistantBubble},s().createElement(o.Icon,{name:"fa fa-spinner",className:c.spinner})," denkt nach ...")),s().createElement("div",{className:c.inputRow},s().createElement(o.TextArea,{"data-testid":l.b.assistantPage.input,placeholder:"Frage stellen...",value:y,rows:2,onChange:e=>x(e.currentTarget.value),onKeyDown:e=>{"Enter"!==e.key||e.shiftKey||(e.preventDefault(),S(y))}}),s().createElement(o.Button,{"data-testid":l.b.assistantPage.send,onClick:()=>S(y),disabled:w},"Senden"))),s().createElement("div",{className:c.contextColumn},s().createElement("div",{className:c.contextTitle},"Verwendeter Kontext"),s().createElement("pre",{className:c.contextText},b)))},m=e=>({layout:r.css`
    display: flex;
    gap: ${e.spacing(2)};
    height: 100%;
    min-height: 0;
  `,layoutNarrow:r.css`
    flex-direction: column;
    height: auto;
  `,chatColumn:r.css`
    flex: 2;
    display: flex;
    flex-direction: column;
    gap: ${e.spacing(1)};
    min-width: 0;
    min-height: 300px;
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
    max-width: 90%;
  `,assistantBubble:r.css`
    align-self: flex-start;
    background: ${e.colors.background.secondary};
    padding: ${e.spacing(1,1.5)};
    border-radius: ${e.shape.radius.default};
    max-width: 90%;
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
  `});a.d(t,["A",0,p])},611(e,t,a){a.d(t,["b",0,{appConfig:{chatBackendUrl:"data-testid ac-chat-backend-url",submit:"data-testid ac-submit-form"},assistantPage:{container:"data-testid assistant-page-container",input:"data-testid assistant-page-input",send:"data-testid assistant-page-send"}}])},640(e,t,a){a.r(t);var n=a(959),s=a.n(n),r=a(89),i=a(531),o=a(7),l=a(278);const c=function(){const e=(0,o.useStyles2)(d);return s().createElement(i.PluginPage,null,s().createElement("div",{className:e.wrapper},s().createElement(l.A,{layout:"wide"})))},d=e=>({wrapper:r.css`
    height: calc(100vh - 200px);
  `});a.d(t,["default",0,c])}}]);
//# sourceMappingURL=640.js.map?_cache=449e2606d51d005e649d