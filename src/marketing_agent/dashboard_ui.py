"""Three-panel local dashboard view; selection is read-only."""

from html import escape
from pathlib import Path
from threading import Lock

from .dashboard_contracts import DraftPreview, PostStatus, VideoList
from .drafts import preview
from .rss_feed import list_videos


class FeedDraftService:
    """Read-only service for the first two dashboard panels.

    Posting must be supplied by the separate guarded posting service. A preview
    never opens Chrome or creates a posting reservation.
    """

    def __init__(self, drafts_dir: str | Path = "drafts", *, feed_loader=list_videos):
        self.drafts_dir = Path(drafts_dir)
        self.feed_loader = feed_loader
        self._videos = {}
        self._lock = Lock()

    def list_videos(self) -> VideoList:
        result = self.feed_loader()
        with self._lock:
            self._videos = {card.video_id: card for card in result.videos}
        return result

    def select_video(self, video_id: str) -> DraftPreview:
        with self._lock:
            card = self._videos.get(video_id)
        if card is None:
            return DraftPreview(video_id, reason_code="VIDEO_NOT_FOUND")
        return preview(card, self.drafts_dir)

    def post_video(self, video_id: str) -> PostStatus:
        return PostStatus("blocked", "POST_SERVICE_UNAVAILABLE", "게시 서비스가 연결되지 않았습니다.")

def _page(token: str) -> bytes:
    # The token stays in this process and the served page, never in URLs or logs.
    safe_token = escape(token, quote=True)
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="session-token" content="{safe_token}"><title>유튜브 댓글 대시보드</title>
<style>
:root{{--ink:#14253a;--muted:#526176;--line:#d9e2ed;--paper:#fff;--bg:#f3f6fa;--blue:#174ea6;--focus:#f5b745;--danger:#9f2f35}}
*{{box-sizing:border-box}}body{{font:16px/1.5 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}
header{{padding:24px clamp(16px,3vw,40px);background:#14253a;color:white}}h1{{font-size:clamp(1.5rem,2.5vw,2.1rem);margin:0}}h2{{font-size:1.2rem;margin:0 0 8px}}p{{margin:8px 0 14px}}.eyebrow{{font-size:.8rem;font-weight:700;letter-spacing:.09em;color:#a6caff;margin:0 0 4px}}.intro{{color:#d8e6fb;max-width:70ch;margin:8px 0 0}}
.workflow{{display:flex;gap:8px;flex-wrap:wrap;padding:16px clamp(16px,3vw,40px) 0;list-style:none;margin:0}}.workflow li{{border:1px solid var(--line);border-radius:999px;background:white;color:var(--muted);padding:6px 12px;font-size:.9rem}}.workflow li.current{{border-color:var(--blue);background:#e9f1ff;color:#123d82;font-weight:700}}
main{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:start;gap:16px;padding:18px clamp(16px,3vw,40px) 40px}}section{{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:20px;min-height:440px;box-shadow:0 8px 28px rgba(25,48,83,.05)}}section.current{{border-color:var(--blue);box-shadow:0 0 0 2px #dbe9ff,0 8px 28px rgba(25,48,83,.07)}}.step-note{{color:var(--muted);font-size:.93rem;min-height:44px}}.empty{{padding:20px;border:1px dashed var(--line);border-radius:12px;color:var(--muted);background:#f8fbff}}
button{{font:inherit;cursor:pointer;min-height:44px;padding:10px 16px;margin:4px 0;border-radius:10px;border:1px solid var(--blue);background:var(--blue);color:white;font-weight:650}}button:hover:not(:disabled):not([aria-disabled="true"]){{background:#123d82}}button:disabled,button[aria-disabled="true"]{{cursor:not-allowed;opacity:.55}}button:focus-visible,summary:focus-visible,textarea:focus-visible{{outline:3px solid var(--focus);outline-offset:2px}}#action-toast{{position:fixed;z-index:1000;right:16px;bottom:16px;max-width:min(420px,calc(100vw - 32px));padding:14px 18px;border-radius:12px;background:#14253a;color:white;box-shadow:0 14px 36px #14253a55}}#action-toast[hidden]{{display:none}}
.card{{display:block;width:100%;text-align:left;border:1px solid var(--line);background:white;color:var(--ink);border-radius:12px;padding:10px;margin:10px 0;min-height:66px;font-weight:400}}.card:hover,.card.selected{{background:#edf4ff;border-color:var(--blue)}}.card strong{{display:block;line-height:1.35}}.card p{{color:var(--muted);font-size:.86rem;margin:4px 0 0}}.card img{{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:7px;margin-bottom:8px}}#videos{{max-height:540px;overflow-y:auto;overscroll-behavior:contain;padding-right:4px;scrollbar-gutter:stable}}
.card.state-posted{{background:#e7f0ff;border-color:#2563ad}}.card.state-ai_generated{{background:#e6f6eb;border-color:#27834b}}.card.state-review{{background:#fff4df;border-color:#b87912}}.card .card-state{{font-weight:700}}
.muted{{color:var(--muted)}}.error{{color:var(--danger)}}.status{{border-radius:10px;padding:10px 12px;background:#edf4ff;color:#163e78}}.status:empty{{display:none}}.status.error{{background:#fff0f0;color:var(--danger)}}.ready{{color:#176442;font-weight:700}}pre{{white-space:pre-wrap;word-break:break-word;font:inherit;background:#f7f9fc;border-radius:10px;padding:12px}}#capture img{{max-width:100%;border-radius:8px}}
label{{display:block;font-weight:650;margin:12px 0 4px}}textarea,input{{font:inherit;width:100%;padding:9px;border:1px solid var(--line);border-radius:8px}}textarea{{min-height:72px;resize:vertical}}.draft-actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.draft-actions button{{margin:0}}.draft-note{{font-size:.86rem;color:var(--muted)}}
.review-box{{border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:10px 0;background:#f7f9fc}}.review-box h3{{margin:0 0 4px;font-size:1rem}}.review-box ul{{margin:4px 0 0;padding-left:18px;font-size:.88rem}}.review-box details{{margin-top:6px}}
.history{{margin:0 clamp(16px,3vw,40px) 40px;min-height:0}}.history-head{{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between}}.history-head h2{{margin:0}}button.secondary{{background:white;color:var(--blue)}}button.secondary:hover:not(:disabled){{background:#edf4ff}}.hist-row{{display:grid;grid-template-columns:150px minmax(0,1fr) 90px 150px;gap:6px 14px;padding:12px 0;border-top:1px solid var(--line);align-items:start}}.hist-row .when{{color:var(--muted);font-size:.86rem;font-variant-numeric:tabular-nums}}.hist-row .comment{{color:var(--ink);font-size:.92rem;margin:4px 0 0;white-space:pre-wrap;word-break:break-word}}.hist-row a{{color:var(--blue)}}.pill{{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.82rem;font-weight:700}}.pill.ok{{background:#e6f6eb;color:#176442}}.pill.fail{{background:#fff0f0;color:var(--danger)}}.pill.warn{{background:#fff4df;color:#8a5a00}}.hist-row .reason{{display:block;color:var(--muted);font-size:.84rem;margin-top:4px}}.hist-row button{{min-height:32px;padding:4px 10px;font-size:.84rem;margin-top:6px}}
@media(max-width:1000px){{main{{grid-template-columns:1fr 1fr}}section:last-child{{grid-column:1/-1;min-height:0}}#videos{{max-height:420px}}}}@media(max-width:680px){{main{{grid-template-columns:1fr}}section,section:last-child{{grid-column:auto;min-height:0}}.workflow{{display:grid;grid-template-columns:1fr}}#videos{{max-height:55dvh}}}}@media(prefers-reduced-motion:reduce){{*,*::before,*::after{{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important}}}}
</style></head>
<body><header><p class="eyebrow">LOCAL WORKSPACE · 3 STEPS</p><h1>유튜브 댓글 대시보드</h1><p class="intro">최신 영상을 확인하고 승인된 초안을 검토한 뒤, 직접 클릭해 댓글을 게시합니다.</p></header>
<ol class="workflow" aria-label="작업 진행"><li id="flow-load" class="current" aria-current="step">1 · 영상 불러오기</li><li id="flow-select">2 · 초안 확인</li><li id="flow-post">3 · 댓글 달기</li></ol><main>
<section id="step-load" class="current" aria-labelledby="heading-load"><h2 id="heading-load">① 영상 불러오기</h2><p class="step-note">설정된 채널의 최신 영상을 확인합니다.</p><button id="load" type="button">영상 불러오기</button><p id="feed-state" class="status" role="status" aria-live="polite"></p><div id="videos" aria-label="영상 목록"><p class="empty">아직 불러온 영상이 없습니다. 위 버튼을 눌러 시작하세요.</p></div></section>
<section id="step-select" aria-labelledby="heading-select"><h2 id="heading-select">② 영상 선택</h2><p class="step-note">목록에서 영상을 고르면 고민과 댓글 초안을 확인할 수 있습니다.</p><div id="selection" class="empty" aria-live="polite">먼저 영상을 불러오세요.</div></section>
<section id="step-post" aria-labelledby="heading-post"><h2 id="heading-post">③ 댓글 달기</h2><p class="step-note">사람이 승인한 초안만 게시할 수 있습니다. 선택만으로 게시되지 않습니다.</p><button id="post" type="button" aria-describedby="post-state">댓글 달기</button><label for="keep-window" style="display:flex;align-items:center;gap:8px;font-weight:500"><input id="keep-window" type="checkbox" style="width:auto">게시 후 Chrome 창 유지 · 댓글 직접 확인</label><p id="post-state" class="status" role="status" aria-live="polite">승인된 초안을 선택하면 게시할 수 있습니다.</p><div id="capture"></div></section>
</main>
<section id="history" class="history" aria-labelledby="heading-history"><div class="history-head"><h2 id="heading-history">④ 실행 기록</h2><span id="history-meter" class="muted"></span><button id="history-refresh" type="button" class="secondary">새로고침</button></div><p class="step-note">어느 영상에 · 어느 프로필로 · 무슨 댓글을 · 성공/실패했는지 최신순으로 보여줍니다.</p><div id="history-list" aria-live="polite"><p class="empty">아직 게시 기록이 없습니다.</p></div></section>
<div id="action-toast" role="status" aria-live="polite" hidden></div><script>
const token=document.querySelector('meta[name="session-token"]').content;
let selected=null,ready=false,profileRequired=false;
const $=id=>document.getElementById(id);
let toastTimer;
function showToast(message){{const toast=$('action-toast');toast.hidden=false;toast.textContent=message;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{{toast.hidden=true;}},4500);}}
function guideButton(button,reason=''){{button.disabled=false;button.setAttribute('aria-disabled',reason?'true':'false');button.dataset.unavailableReason=reason;}}
document.addEventListener('click',event=>{{const button=event.target.closest?.('button[aria-disabled="true"]');if(!button)return;event.preventDefault();event.stopImmediatePropagation();showToast(button.dataset.unavailableReason||'먼저 필요한 설정을 완료해주세요.');}},true);
guideButton($('post'),'먼저 영상을 불러와 선택하고 AI 초안을 검토·승인해주세요.');
function setStep(step){{for(const name of ['load','select','post']){{const active=name===step;const flow=$('flow-'+name);flow.classList.toggle('current',active);if(active)flow.setAttribute('aria-current','step');else flow.removeAttribute('aria-current');$('step-'+name).classList.toggle('current',active);}}}}
async function json(response){{let value=await response.json();if(!response.ok)throw Error(value.reason_code==='FORBIDDEN'?'대시보드 연결이 만료됐거나 거부됐습니다. 페이지를 새로고침한 뒤 다시 시도하세요.':value.reason_code||'REQUEST_FAILED');return value;}}
function line(parent,tag,value){{const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}}
async function localPost(path,body){{return json(await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json','X-Session-Token':token}},body:JSON.stringify(body)}}));}}
async function loadCapture(path){{
 if(!path.startsWith('/captures/'))return;
 const response=await fetch(path,{{headers:{{'X-Session-Token':token}}}});
 if(!response.ok)return;
 const blob=await response.blob();
 const image=document.createElement('img');const url=URL.createObjectURL(blob);image.src=url;
 image.alt='실패 화면 캡처';image.style.maxWidth='100%';
 image.onload=()=>URL.revokeObjectURL(url);$('capture').replaceChildren(image);
}}
function showEvidence(panel,draft){{
 const details=document.createElement('details');details.className='draft-evidence';
 const summary=document.createElement('summary');summary.textContent='초안 근거 원문 확인';details.append(summary);
 if(draft.evidence_sources?.length)line(details,'p','출처: '+draft.evidence_sources.join(' · ')).className='draft-note';
 if(draft.source_text)line(details,'pre',draft.source_text);
 else line(details,'p','저장된 근거 원문이 없습니다. 이전 초안은 영상 원문을 별도로 확인하세요.').className='draft-note';
 panel.append(details);
}}
function editor(panel,draft){{
 showEvidence(panel,draft);
 const minChars=draft.min_chars??40,maxChars=draft.max_chars??120;
 const fields=[['worry_summary','고민 한 줄',draft.worry_summary||''],['cited_detail','근거 원문에서 확인한 표현',draft.cited_detail||''],['comment','댓글 초안',draft.comment||''],['reviewer','검토자 이름','']];
 line(panel,'h3','사람 검토 및 승인');line(panel,'p','AI 제안은 승인 전에는 게시할 수 없습니다. 위 근거 원문과 인용 표현을 대조하고 수정하세요.').className='draft-note';
 for(const [name,label,value] of fields){{const labelEl=document.createElement('label');labelEl.htmlFor='draft-'+name;labelEl.textContent=label;panel.append(labelEl);const input=name==='comment'?document.createElement('textarea'):document.createElement('input');input.id='draft-'+name;input.value=value;input.maxLength=name==='comment'?maxChars:1000;panel.append(input);}}
 const lengthState=line(panel,'p','');lengthState.className='draft-note';const actions=document.createElement('div');actions.className='draft-actions';const approve=document.createElement('button');approve.type='button';approve.textContent='승인하고 저장';
 function updateCommentLength(){{const length=$('draft-comment').value.trim().length;const valid=length>=minChars&&length<=maxChars;const range=minChars+'~'+maxChars+'자';lengthState.textContent=length+'자 / '+range+(valid?'':' · 범위에 맞게 댓글을 수정하세요.');lengthState.classList.toggle('error',!valid);guideButton(approve,valid?'':'댓글을 '+range+'로 수정한 뒤 승인해주세요.');}}
 $('draft-comment').addEventListener('input',updateCommentLength);updateCommentLength();
 approve.addEventListener('click',async()=>{{guideButton(approve,'초안을 저장하는 중입니다. 잠시 기다려주세요.');try{{const values=Object.fromEntries(fields.map(([name])=>[name,$('draft-'+name).value]));const saved=await localPost('/api/drafts/approve',{{video_id:selected,draft:values}});await selectVideo(saved.video_id);line($('selection'),'p','승인된 초안을 저장했습니다.').className='ready';}}catch(error){{const why=(typeof explainReason==='function'?explainReason(error.message):error.message);line(panel,'p','승인하지 못했습니다: '+why).className='status error';showToast('초안 승인에 실패했습니다: '+why);}}finally{{if(document.body.contains(approve))updateCommentLength();}}}});actions.append(approve);panel.append(actions);
}}
const REVIEW_LABEL={{LENGTH:'글자 수',RULE:'금지 규칙',QUOTE_TOO_LONG:'인용 길이',SAME_QUOTE:'다른 영상과 같은 인용',GENERIC:'일반적인 칭찬',REPEATED_CLOSING:'다른 영상과 같은 운명원 문장'}};
function showReview(panel,data){{const box=document.createElement('div');box.className='review-box';const rounds=data.review_rounds||[];const remaining=data.problems||[];
 line(box,'h3','2차 필터 결과');
 if(data.review_filter===false&&!rounds.length)line(box,'p','2차 필터가 꺼져 있습니다. 설정 → 댓글 생성 관리에서 켤 수 있습니다.').className='draft-note';
 const fixes=Math.max(rounds.length-1,0);line(box,'p',fixes?('AI가 '+fixes+'번 고쳐 썼습니다.'+(data.changed?' (이번 요청에서 갱신됨)':'')):'고쳐 쓴 기록이 없습니다.').className='draft-note';
 if(remaining.length){{line(box,'p','남은 지적 '+remaining.length+'건 · "2차 필터 다시 적용"으로 고치거나 직접 수정하세요.').className='status error';const list=document.createElement('ul');for(const item of remaining){{const code=item.split(':')[0].split(' ')[0];line(list,'li',(REVIEW_LABEL[code]||code)+' — '+item.slice(item.indexOf(':')+1).trim());}}box.append(list);}}
 else line(box,'p','현재 검사 기준으로 남은 지적이 없습니다.').className='ready';
 if(rounds.length>1){{const d=document.createElement('details');line(d,'summary','고쳐 쓴 과정 보기');rounds.forEach((r,i)=>{{line(d,'p',(i===rounds.length-1?'최종':(i+1)+'차')+': '+r.comment).className='draft-note';}});box.append(d);}}
 panel.append(box);}}
function createReviewButtons(panel){{const row=document.createElement('div');row.className='draft-actions';
 const open=document.createElement('button');open.type='button';open.className='secondary';open.textContent='검토·승인 화면 열기';
 const again=document.createElement('button');again.type='button';again.className='secondary';again.textContent='2차 필터 다시 적용';
 async function run(rewrite,button){{const label=button.textContent;guideButton(open,'처리 중입니다.');guideButton(again,'처리 중입니다.');button.textContent=rewrite?'필터 적용 중…':'불러오는 중…';
  try{{const data=await localPost('/api/drafts/refine',{{video_id:selected,rewrite}});panel.replaceChildren();
   line(panel,'p',rewrite?(data.changed?'2차 필터로 초안을 고쳐 저장했습니다. 다시 검토하고 승인해주세요.':'고칠 지적이 없거나 AI가 더 나은 안을 내지 못해 초안을 그대로 두었습니다.'):(data.approved?'승인된 초안입니다. 고치면 다시 승인해야 합니다.':'저장된 초안을 검토하고 승인해주세요.')).className='status';
   showReview(panel,data);editor(panel,data);
   if(rewrite&&data.changed){{ready=false;guideButton($('post'),'고쳐 쓴 초안을 검토·승인한 뒤 댓글을 달 수 있습니다.');}}
  }}catch(error){{showToast(error.message==='AI_KEY_MISSING'?'2차 필터를 다시 적용하려면 옵션 → AI API 관리에서 AI 키를 입력하세요.':'처리하지 못했습니다: '+error.message);button.textContent=label;guideButton(open,'');guideButton(again,'');}}}}
 open.addEventListener('click',()=>run(false,open));again.addEventListener('click',()=>run(true,again));
 row.append(open,again);panel.append(row);}}
function createDraftButton(panel){{const action=document.createElement('button');action.type='button';action.textContent='AI 초안 만들기';guideButton(action,'AI 설정을 확인하는 중입니다. 잠시 기다려주세요.');action.addEventListener('click',async()=>{{let blockedReason='';guideButton(action,'AI 초안을 생성하는 중입니다. 잠시 기다려주세요.');try{{const draft=await localPost('/api/drafts/generate',{{video_id:selected}});panel.replaceChildren();line(panel,'p','AI 초안을 저장했습니다. 사람 검토와 승인이 필요합니다.').className='status';if(draft.evidence_sources?.length)line(panel,'p','AI 근거: '+draft.evidence_sources.join(' · ')).className='draft-note';if(draft.evidence_notice){{const notice=line(panel,'p',draft.evidence_notice);notice.className='draft-note';if(draft.evidence_notice.includes('키가 유효하지')){{const setup=document.createElement('button');setup.type='button';setup.textContent='키 설정하기';setup.className='secondary';setup.style.cssText='font-size:.8rem;padding:4px 8px;margin-left:8px';setup.addEventListener('click',()=>$('ai-menu-open').click());notice.append(setup);}}}}showReview(panel,draft);editor(panel,draft);}}catch(error){{line(panel,'p','AI 초안을 만들지 못했습니다: '+error.message).className='status error';blockedReason=['AI_KEY_MISSING','AI_AUTH_FAILED'].includes(error.message)?'우측 상단의 옵션 → AI API 관리에서 AI API 키를 입력하고 연결 테스트를 해주세요.':'';showToast(blockedReason||'AI 초안을 만들지 못했습니다. 오류 안내를 확인하고 다시 시도해주세요.');}}finally{{if(document.body.contains(action))guideButton(action,blockedReason);}}}});panel.append(action);if(typeof checkAiDraftAvailability==='function')checkAiDraftAvailability(action);else guideButton(action,'');}}
async function loadVideos(){{selected=null;ready=false;profileRequired=false;setStep('load');guideButton($('load'),'영상을 불러오는 중입니다. 잠시 기다려주세요.');guideButton($('post'),'먼저 영상을 선택하고 AI 초안을 검토·승인해주세요.');$('selection').className='empty';$('selection').textContent='영상 목록에서 하나를 선택하세요.';$('post-state').textContent='승인된 초안을 선택하면 게시할 수 있습니다.';$('videos').replaceChildren();$('feed-state').classList.remove('error');$('feed-state').textContent='영상을 불러오는 중입니다…';
try{{const data=await json(await fetch('/api/videos',{{headers:{{'X-Session-Token':token}}}}));$('feed-state').textContent=data.videos.length?data.videos.length+'개 영상을 불러왔습니다. 영상을 선택하세요.':'표시할 영상이 없습니다. 채널 설정과 RSS 응답을 확인하세요.';
if(!data.videos.length)line($('videos'),'p','목록이 비어 있습니다. 설정을 확인한 뒤 다시 불러오세요.').className='empty';
for(const video of data.videos){{const button=document.createElement('button');const state=data.states?.[video.video_id]||{{profile:'',state:'unassigned'}};button.className='card state-'+state.state;button.type='button';button.dataset.videoId=video.video_id;
const image=document.createElement('img');image.src=video.thumbnail_url;image.alt='영상 썸네일';button.append(image);
line(button,'strong',video.title);line(button,'p',video.channel+' · '+video.published_at);const stateLabel={{posted:'댓글 게시 완료',ai_generated:'AI 초안 생성',review:'게시 결과 확인 필요',not_started:'미작성',unassigned:'담당 프로필 없음'}}[state.state]||'상태 확인 필요';line(button,'p',(state.profile||'미배정')+' · '+stateLabel).className='card-state';button.addEventListener('click',()=>selectVideo(video.video_id));$('videos').append(button);}}
for(const [channel,error] of Object.entries(data.errors))line($('videos'),'p',channel+': '+(typeof rssText==='function'?rssText(error):error)).className='status error';
if(data.videos.length)setStep('select');
}}catch(error){{$('feed-state').classList.add('error');$('feed-state').textContent='영상 목록을 불러오지 못했습니다: '+error.message;}}finally{{guideButton($('load'));}}}}
async function selectVideo(id){{selected=id;ready=false;profileRequired=false;setStep('select');guideButton($('post'),'초안을 확인하는 중입니다. 잠시 기다려주세요.');$('selection').className='status';$('selection').textContent='초안을 확인하는 중입니다…';$('post-state').textContent='초안을 확인하고 있습니다.';
try{{const draft=await json(await fetch('/api/videos/'+encodeURIComponent(id)+'/draft',{{headers:{{'X-Session-Token':token}}}}));if(selected!==id)return;
for(const card of document.querySelectorAll('.card'))card.classList.remove('selected');for(const card of document.querySelectorAll('.card'))if(card.dataset.videoId===id)card.classList.add('selected');
const panel=$('selection');panel.className='';panel.replaceChildren();const missing=draft.reason_code==='DRAFT_MISSING';if(missing){{line(panel,'h3','아직 댓글 초안이 없습니다.');line(panel,'p','AI 초안을 만든 뒤 내용을 검토하고 승인해주세요.').className='status';}}else{{line(panel,'h3','고민 한 줄');line(panel,'p',draft.worry_summary||'준비된 고민 요약이 없습니다.');line(panel,'h3','댓글 초안');line(panel,'pre',draft.comment||'준비된 댓글 초안이 없습니다.');}}if(!missing)showEvidence(panel,draft);
const defaultChromeRoot=draft.reason_code==='DEFAULT_CHROME_USER_DATA_DIR_UNSUPPORTED';const profileIssue=(String(draft.reason_code).startsWith('PROFILE_')&&draft.reason_code!=='PROFILE_LOCKED')||String(draft.reason_code).startsWith('USER_DATA_')||defaultChromeRoot;const profileMessage=defaultChromeRoot?'현재 기본 Chrome 데이터 폴더는 자동화에 사용할 수 없습니다. 자동화 전용 폴더를 준비하고 해당 Chrome에서 직접 로그인하세요.':'Chrome 프로필을 연결하면 댓글 달기를 계속할 수 있습니다.';if(!missing)line(panel,'p',draft.can_post?'승인된 초안입니다. 내용을 검토한 뒤 직접 게시하세요.':profileIssue?profileMessage:'게시 불가: '+draft.reason_code).className=draft.can_post?'ready':profileIssue?'status':'status error';ready=draft.can_post;profileRequired=profileIssue;guideButton($('post'),ready||profileRequired?'':missing?'먼저 AI 초안을 만들고 내용을 검토·승인해주세요.':draft.reason_code==='PROFILE_LOCKED'?'앱 전용 Chrome 창을 닫은 뒤 영상을 다시 선택해주세요.':'게시 조건을 확인하고 초안을 승인해주세요.');$('post-state').textContent=draft.can_post?'초안 검토 후 댓글 달기를 누르세요.':missing?'AI 초안을 만들고 사람이 승인하면 댓글을 달 수 있습니다.':draft.reason_code==='PROFILE_LOCKED'?'앱 전용 Chrome 로그인 창을 정상 종료한 뒤 영상을 다시 선택하세요.':profileIssue?'댓글 달기를 누르면 Chrome 프로필 연결을 시작합니다.':'AI 초안을 만들고 사람이 승인하면 게시할 수 있습니다.';if(draft.can_post||profileIssue||draft.reason_code==='PROFILE_LOCKED')setStep('post');if(profileIssue)createProfileButton(panel);else if(!draft.can_post&&draft.reason_code!=='PROFILE_LOCKED')createDraftButton(panel);if(!missing&&!profileIssue&&draft.reason_code!=='PROFILE_LOCKED')createReviewButtons(panel);
}}catch(error){{if(selected===id){{$('selection').className='status error';$('selection').textContent='초안을 확인하지 못했습니다: '+error.message;$('post-state').textContent='초안 확인에 실패해 게시할 수 없습니다.';guideButton($('post'),'초안 확인에 실패했습니다. 영상을 다시 선택해주세요.');}}}}}}
async function postComment(){{if(!selected)return;if(profileRequired){{openProfileDialog();return;}}if(!ready)return;guideButton($('post'),'게시 결과를 확인하는 중입니다. 중복 게시를 막기 위해 기다려주세요.');$('post-state').classList.remove('error');$('post-state').textContent='게시 요청을 확인하고 있습니다. 결과를 확인할 때까지 다시 누르지 마세요.';
try{{const response=await fetch('/api/post',{{method:'POST',headers:{{'Content-Type':'application/json','X-Session-Token':token}},body:JSON.stringify({{video_id:selected,keep_window_open:$('keep-window').checked}})}});
const result=await response.json();
$('post-state').textContent=[result.state,result.reason_code,result.message].filter(Boolean).join(' · ');$('post-state').classList.toggle('error',result.state!=='posted'&&result.state!=='simulated');
if(result.screenshot_url)await loadCapture(result.screenshot_url);if(result.reason_code==='LOGIN_REQUIRED'&&typeof openLoginAfterPost==='function')await openLoginAfterPost();
}}catch(error){{$('post-state').classList.add('error');$('post-state').textContent='게시 결과를 확인하지 못했습니다: '+error.message+' · 자동 재시도하지 않습니다.';}}}}
const HIST_STATUS={{POSTED:['게시 완료','ok'],PRECHECK_FAILED:['게시 전 중단','fail'],OUTCOME_UNKNOWN:['결과 확인 필요','warn'],RESERVED:['진행 중','warn'],SUBMITTING:['진행 중','warn']}};
const REASON_KO={{LOGIN_REQUIRED:'로그인 필요',PROFILE_LOCKED:'프로필 창이 열려 있음',BROWSER_LAUNCH_FAILED:'Chrome 실행 실패',ChromeLaunchFailed:'Chrome 실행 실패',YOUTUBE_NAVIGATION_FAILED:'YouTube 화면 이동 실패',COMMENT_EDITOR_MISSING:'댓글 입력창 없음',COMMENT_NOT_CONFIRMED:'게시 후 내 댓글 확인 실패',SERVER_RESTART_BEFORE_SUBMIT:'게시 전 서버 재시작',DAILY_LIMIT:'하루 상한 도달',ALREADY_ATTEMPTED:'이미 시도한 영상',CHANNEL_COOLDOWN:'같은 채널에는 60분 간격으로만 댓글을 달 수 있습니다. 다른 채널 영상을 선택하거나 잠시 뒤 다시 시도하세요.'}};
async function loadHistory(){{const list=$('history-list');try{{const data=await json(await fetch('/api/history',{{headers:{{'X-Session-Token':token}}}}));
 $('history-meter').textContent=data.unavailable?'연습 모드에는 기록이 없습니다.':'오늘 게시 '+data.posted_today+' / '+data.daily_limit;
 if(!data.items.length){{list.replaceChildren();line(list,'p','아직 게시 기록이 없습니다.').className='empty';return;}}
 list.replaceChildren();for(const item of data.items){{const row=document.createElement('div');row.className='hist-row';
  const when=new Date(item.reserved_at);line(row,'span',isNaN(when)?item.reserved_at:when.toLocaleString('ko-KR',{{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}})).className='when';
  const main=document.createElement('div');line(main,'strong',item.title);const link=document.createElement('a');link.href='https://www.youtube.com/watch?v='+encodeURIComponent(item.video_id);link.target='_blank';link.rel='noopener';link.textContent=' 영상 열기';main.append(link);
  line(main,'p',item.comment||'(댓글 본문 기록 없음)').className='comment';row.append(main);
  line(row,'span',item.profile).className='profile';
  const state=document.createElement('div');const [label,tone]=HIST_STATUS[item.status]||[item.status,'warn'];line(state,'span',label).className='pill '+tone;
  if(item.reason_code)line(state,'span',REASON_KO[item.reason_code]||item.reason_code).className='reason';
  if(item.screenshot_url){{const shot=document.createElement('button');shot.type='button';shot.className='secondary';shot.textContent='실패 캡처 보기';shot.addEventListener('click',()=>loadCapture(item.screenshot_url));state.append(shot);}}
  row.append(state);list.append(row);}}
}}catch(error){{list.replaceChildren();line(list,'p','실행 기록을 불러오지 못했습니다: '+error.message).className='status error';}}}}
$('load').addEventListener('click',loadVideos);$('post').addEventListener('click',async()=>{{await postComment();loadHistory();}});
$('history-refresh').addEventListener('click',loadHistory);loadHistory();
</script></body></html>'''.encode("utf-8")



page = _page

