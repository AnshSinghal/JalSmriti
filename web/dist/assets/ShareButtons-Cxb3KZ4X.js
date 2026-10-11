import{j as e}from"./motion-BhhR4jgw.js";import{r as d}from"./react-Bu9c7T3F.js";import{g as p,u as l}from"./index-D1EikCdH.js";import{C as m}from"./check-DseFafmo.js";import{C as u}from"./copy-DqHMt2Re.js";/**
 * @license lucide-react v0.454.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=p("MessageCircle",[["path",{d:"M7.9 20A9 9 0 1 0 4 16.1L2 22Z",key:"vv11sd"}]]);function g({text:n,path:r}){const{t}=l(),[s,a]=d.useState(!1),o=r?`${window.location.origin}${r}`:window.location.href,c=`https://wa.me/?text=${encodeURIComponent(`${n} ${o}`)}`;return e.jsxs(e.Fragment,{children:[e.jsxs("a",{className:"btn-quiet",href:c,target:"_blank",rel:"noreferrer",children:[e.jsx(h,{size:16,"aria-hidden":"true"})," ",t("share.whatsapp")]}),e.jsxs("button",{className:"btn-quiet",onClick:()=>{var i;(i=navigator.clipboard)==null||i.writeText(o),a(!0),setTimeout(()=>a(!1),1800)},children:[s?e.jsx(m,{size:16,"aria-hidden":"true"}):e.jsx(u,{size:16,"aria-hidden":"true"})," ",t(s?"place.copied":"place.share")]})]})}export{g as S};
