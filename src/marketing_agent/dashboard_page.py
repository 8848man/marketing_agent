"""Render the dashboard page without HTTP or posting side effects."""

import json
from html import escape

from .ai_client import PROVIDER_DETAILS
from .dashboard_ui import _page as base_page
from .rss_feed import CHANNELS


def render_page(token: str, *, demo: bool = False) -> bytes:
    page = base_page(token).decode("utf-8")
    provider_options = "".join(
        f'<option value="{escape(name)}">{escape(details["label"])}</option>'
        for name, details in PROVIDER_DETAILS.items())
    provider_presets = {name: [dict(id=model, label=label, recommended=index == 0)
                               for index, (model, label) in enumerate(details["presets"])]
                        for name, details in PROVIDER_DETAILS.items()}
    profile_markup = """
<style>.profile-dialog{border:0;border-radius:16px;padding:0;width:min(620px,calc(100vw - 32px));max-height:85dvh}.profile-dialog::backdrop{background:rgba(20,37,58,.55)}.profile-dialog form{padding:22px;overflow:auto;max-height:85dvh}.profile-dialog h2{margin-top:0}.profile-dialog menu{display:flex;gap:8px;justify-content:flex-end;padding:0;margin:18px 0 0}.profile-dialog menu button{margin:0}.profile-help{color:#526176;font-size:.9rem}.profile-list{display:grid;gap:10px;margin:16px 0;max-height:330px;overflow-y:auto;overscroll-behavior:contain;padding-right:6px}.profile-row{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:96px;padding:12px;border:2px solid #b6c4d3;border-radius:10px}.profile-row.selected{background:#e8f3ff;border-color:#1768b6}.profile-row strong,.profile-row span{display:block}.profile-row button{margin:0;white-space:nowrap}.profile-row span{font-size:.85rem;color:#36516f}.profile-info{flex:1;min-width:200px}.profile-heading{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.profile-change{font-size:.75rem;padding:4px 8px;min-height:28px}.profile-email{max-width:260px;min-width:150px;flex:1;margin:0!important}.profile-add-form{display:flex;align-items:end;gap:8px;margin-top:10px;padding:12px;background:#f2f6fc;border-radius:10px}.profile-add-form[hidden]{display:none}.profile-add-form label{flex:1;font-weight:650}.profile-add-form input{display:block;width:100%;min-height:44px;margin-top:6px;padding:9px;border:1px solid #8b9bb0;border-radius:8px;font:inherit}</style>
<dialog id="profile-dialog" class="profile-dialog" aria-labelledby="profile-title"><form method="dialog"><h2 id="profile-title" tabindex="-1">앱 전용 Chrome 프로필</h2><p class="profile-help">현재 계정 확인은 해당 전용 Chrome으로 우리 채널 영상 페이지를 열어 로그인 여부만 확인합니다(이메일은 읽지 않음). 로그아웃이면 같은 영상 페이지를 열어 드리니, 오른쪽 위 “로그인”을 직접 눌러 로그인한 뒤 창을 닫고 다시 확인하세요.</p><div id="profile-list" class="profile-list" role="list" aria-label="앱 전용 프로필 목록"></div><button id="profile-setup" type="button">미연결 프로필 추가</button><div id="profile-add-form" class="profile-add-form" hidden><label for="profile-add-name">새 프로필 이름<input id="profile-add-name" type="text" maxlength="30" autocomplete="off" placeholder="예: 브랜드 계정"></label><button id="profile-add-save" type="button">등록</button><button id="profile-add-cancel" type="button" class="secondary">취소</button></div><p id="profile-state" class="status" role="status" aria-live="polite"></p><menu><button id="profile-cancel" type="button">닫기</button></menu></form></dialog>
"""
    page = page.replace("<script>", profile_markup + "<script>", 1)
    page = page.replace('<div id="capture"></div>', '<button id="post-continue" type="button" hidden>댓글 계속하기</button><div id="capture"></div>', 1)
    advanced_panel = ""
    reason_labels = """
const reasonText={
  TEST_FEED_UNAVAILABLE:'테스트 영상 채널 RSS 조회 실패: 네트워크를 확인하고 다시 선택하세요. 게시하지 않았습니다.',
  TEST_VIDEO_NOT_IN_FEED:'테스트 영상이 채널 RSS에 없습니다. 최신 목록 범위 밖일 수 있어 게시하지 않았습니다.',
  TEST_VIDEO_CHANGED:'테스트 영상의 채널 또는 제목이 등록 정보와 다릅니다. 확인 후 다시 등록하세요.',
  AI_EMPTY_RESPONSE:'AI가 빈 응답을 반환했습니다. 잠시 후 다시 시도하거나 모델 설정을 확인하세요.',
  AI_RESPONSE_INVALID:'AI 응답이 초안 JSON 형식이 아닙니다. 모델 설정을 확인하고 다시 시도하세요.',
  PROFILE_LOCKED:'앱 전용 Chrome 창이 열려 있습니다. 창을 닫은 뒤 다시 확인하세요.',
  PROFILE_EMAIL_NOT_VISIBLE:'YouTube 계정 메뉴에서 현재 계정 이메일을 확인하지 못했습니다. 로그인 상태를 확인하세요.',
  PROFILE_SIGNED_OUT:'YouTube 로그아웃 상태가 확인됐습니다.',
  PROFILE_ACCOUNT_UNKNOWN:'현재 YouTube 로그인 상태를 정확히 확인하지 못했습니다.',
  PROFILE_NAME_DUPLICATE:'이미 사용 중인 프로필 이름입니다.',
  PROFILE_NAME_INVALID:'프로필 이름은 1~30자로 입력하고 경로 문자는 제외하세요.',
  PROFILE_LIMIT_REACHED:'프로필은 최대 20개까지 등록할 수 있습니다.',
  BRAND_CHANGED_REGENERATE:'브랜드명·설명 또는 글자 수 범위가 바뀌었습니다. AI 초안을 다시 만들고 검토·승인하세요.',
  BROWSER_LAUNCH_FAILED:'Chrome을 열지 못했습니다. 앱 전용 Chrome 창을 모두 정상 종료한 뒤 영상을 다시 선택해 시도하세요. 계속 실패하면 Chrome 실행 상태를 확인하세요.',
  DEMO_NO_POST:'실제 게시 없음'
};
const explainReason=code=>reasonText[code]||code;
const stateText=state=>({posted:'게시 확인',simulated:'연습 완료',blocked:'게시 차단'}[state]||state);
"""
    page = page.replace("</script>", reason_labels + "</script>")
    page = page.replace("'게시 불가: '+draft.reason_code", "'게시 불가: '+explainReason(draft.reason_code)")
    page = page.replace("[result.state,result.reason_code,result.message]",
                        "[stateText(result.state),explainReason(result.reason_code),result.message]")
    if demo:
        banner = ('<aside role="status" style="padding:12px 24px;background:#fff1ba;'
                  'color:#332600;font-weight:700">오프라인 연습 모드: 예시 자료만 표시합니다. '
                  'YouTube 요청·게시용 Chrome 프로필 실행·DB 예약·실제 게시를 하지 않습니다.</aside>')
        page = page.replace("</header>", "</header>" + banner, 1)
        page = page.replace("설정된 채널의 최신 영상을 확인합니다.",
                            "가상 영상으로 세 단계 조작을 연습합니다.", 1)
        page = page.replace("image.src=video.thumbnail_url;",
                            "if(video.thumbnail_url)image.src=video.thumbnail_url;else image.hidden=true;", 1)
    dialog_style = """
header{position:relative;padding-right:118px}#options-open{position:absolute;right:clamp(16px,3vw,40px);top:25px;background:#fff;color:#14253a;border-color:#fff}.options-menu{position:absolute;right:clamp(16px,3vw,40px);top:76px;z-index:10;width:190px;padding:6px;border:1px solid #d9e2ed;border-radius:12px;background:white;box-shadow:0 18px 42px rgba(10,25,45,.25)}.options-menu[hidden]{display:none}.options-menu button{display:block;width:100%;padding:12px;text-align:left;background:white;color:#14253a;border:0;border-radius:8px}.options-menu button:hover,.options-menu button:focus-visible{background:#eaf2ff}
dialog.channel-dialog{width:min(720px,calc(100vw - 24px));max-height:min(720px,85dvh);padding:0;border:1px solid #d9e2ed;border-radius:18px;box-shadow:0 28px 80px rgba(10,25,45,.3);color:#14253a;overflow:hidden}
dialog.channel-dialog[open]{display:grid;grid-template-rows:auto minmax(0,1fr) auto}dialog.channel-dialog::backdrop{background:rgba(10,24,43,.6)}
.dialog-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 20px;background:#f2f6fc;color:#14253a;border-bottom:1px solid #d9e2ed}.dialog-head h2{margin:0}.dialog-head button,.dialog-actions .secondary,.channel-row button.secondary{background:white;color:#174ea6}
.dialog-scroll{overflow-y:auto;overscroll-behavior:contain;padding:14px 20px}.dialog-actions{display:flex;justify-content:flex-end;align-items:center;gap:10px;padding:12px 20px;background:white;border-top:1px solid #d9e2ed}.channel-row{display:grid;grid-template-columns:minmax(150px,1fr) minmax(210px,1.35fr) auto auto;align-items:end;gap:8px;margin:12px 0;padding:12px;border:1px solid #d9e2ed;border-radius:12px}.channel-row label{display:block;font-weight:650}.channel-row input,.channel-row select{display:block;width:100%;min-height:44px;margin-top:6px;padding:9px;border:1px solid #8b9bb0;border-radius:8px;font:inherit}.channel-row .row-state{grid-column:1/-1;margin:0;font-size:.9rem}.channel-row .candidate-box{display:flex;align-items:end;gap:8px;margin-top:8px}.channel-row .candidate-box select{flex:1}.channel-row button{white-space:nowrap}.channel-count{color:#526176}.demo-hint{background:#fff1ba;padding:10px;border-radius:8px}
.ai-field{display:block;margin:16px 0;font-weight:650}.ai-field[hidden]{display:none}.ai-field select,.ai-field input{display:block;width:100%;min-height:44px;margin-top:6px;padding:9px;border:1px solid #8b9bb0;border-radius:8px;font:inherit}.ai-check{display:flex;align-items:center;gap:8px;min-height:44px}.ai-help{color:#526176;font-size:.95rem}.ai-key-status{padding:10px;border-radius:8px;background:#eef5ff}.ai-dialog .dialog-actions{flex-wrap:wrap}.ai-dialog .dialog-actions #ai-test{margin-right:auto}
@media(max-width:720px){header{padding-right:90px}#options-open{right:16px;top:18px;padding:8px}.channel-row{grid-template-columns:1fr 1fr}.channel-row label{grid-column:1/-1}.channel-row button{width:100%}.dialog-actions{flex-wrap:wrap}}
"""
    page = page.replace("</style>", dialog_style + "</style>", 1)
    page = page.replace("</header>",
                        '''<button id="options-open" type="button" aria-haspopup="menu" aria-controls="options-menu" aria-expanded="false">설정</button>
<div id="options-menu" class="options-menu" role="menu" hidden><button id="channel-menu-open" type="button" role="menuitem">채널 관리</button><button id="profile-menu-open" type="button" role="menuitem">Chrome 프로필 관리</button><button id="brand-menu-open" type="button" role="menuitem">댓글 생성 관리</button><button id="ai-menu-open" type="button" role="menuitem">AI API 관리</button></div></header>''', 1)
    dialog_html = '''<dialog id="channel-dialog" class="channel-dialog" aria-labelledby="channel-title">
<div class="dialog-head"><h2 id="channel-title" tabindex="-1">채널 관리</h2><button id="channel-close" type="button" class="secondary" aria-label="채널 관리 닫기">닫기</button></div>
<div class="dialog-scroll"><p>채널 ID는 필수입니다. 채널명은 선택 사항이며, 비워 두면 연결 테스트에서 RSS의 채널명을 확인해 채웁니다. 연결 테스트는 채널 소유권을 증명하지 않습니다.</p>
<p id="channel-count" class="channel-count" role="status"></p><div id="channel-rows"></div>
<button id="channel-add" type="button" class="secondary">+ 채널 추가</button>
<p id="channel-state" class="status" role="status" aria-live="polite"></p></div>
<div class="dialog-actions"><button id="channel-cancel" type="button" class="secondary">취소</button><button id="channel-save" type="button">채널 저장</button></div>
</dialog>'''
    page = page.replace('<ol class="workflow"', dialog_html + '<ol class="workflow"', 1)
    ai_dialog = '''<dialog id="ai-dialog" class="channel-dialog ai-dialog" aria-labelledby="ai-title">
<div class="dialog-head"><h2 id="ai-title" tabindex="-1">AI API 관리</h2><button id="ai-close" type="button" class="secondary" aria-label="AI API 관리 닫기">닫기</button></div>
<div class="dialog-scroll"><p>제공사와 모델을 선택하고 API 키를 로컬에 저장합니다. 연결 테스트는 저장 후 직접 누를 때만 AI에 요청합니다. 댓글 초안 생성과 게시는 이 화면에서 실행되지 않습니다.</p>
<label class="ai-field" for="ai-provider">AI 제공사<select id="ai-provider">__PROVIDER_OPTIONS__</select></label>
<label class="ai-field" for="ai-model-choice">모델 ID<select id="ai-model-choice"></select></label>
<label class="ai-field" for="ai-model-custom" id="ai-custom-wrap" hidden>직접 입력할 모델 ID<input id="ai-model-custom" type="text" maxlength="80" autocomplete="off" spellcheck="false" placeholder="제공사의 정확한 모델 ID"></label>
<p class="ai-help">모델 ID는 제공사별로 바뀔 수 있습니다. 목록에 없다면 직접 입력을 선택하세요.</p>
<label class="ai-field" for="ai-key">API 키 · 새 키로 교체할 때만 입력<input id="ai-key" type="password" maxlength="4096" autocomplete="off" spellcheck="false" placeholder="비워 두면 같은 제공사의 저장된 키 유지"></label>
<p id="ai-key-status" class="ai-key-status" role="status"></p>
<label class="ai-check"><input id="ai-clear-key" type="checkbox"> 저장된 로컬 키 삭제</label>
<p class="ai-help">다른 제공사로 바꾸면 이전 키는 재사용하지 않습니다. 환경변수 키는 이 화면에서 삭제할 수 없습니다.</p>
<label class="ai-field" for="youtube-key">YouTube Data API 키 · 새 키로 교체할 때만 입력<input id="youtube-key" type="password" maxlength="256" autocomplete="off" spellcheck="false" placeholder="기존 키는 표시하지 않습니다"></label><button id="youtube-key-save" type="button" class="secondary">YouTube 키 저장</button><p id="ai-state" class="status" role="status" aria-live="polite"></p></div>
<div class="dialog-actions"><button id="ai-test" type="button" class="secondary">AI 연결 테스트</button><button id="ai-cancel" type="button" class="secondary">취소</button><button id="ai-save" type="button">AI 설정 저장</button></div>
</dialog>'''
    page = page.replace('<ol class="workflow"', ai_dialog.replace('__PROVIDER_OPTIONS__', provider_options) + '<ol class="workflow"', 1)
    brand_dialog = '''<dialog id="brand-dialog" class="channel-dialog" aria-labelledby="brand-title">
<div class="dialog-head"><h2 id="brand-title" tabindex="-1">댓글 생성 관리</h2><button id="brand-close" type="button" class="secondary" aria-label="댓글 생성 관리 닫기">닫기</button></div>
<div class="dialog-scroll"><p>AI 초안은 브랜드명·설명과 글자 수 범위를 참고해 댓글을 만듭니다.</p>
<label class="ai-field" for="brand-name">브랜드명 · 필수<input id="brand-name" type="text" required maxlength="80" autocomplete="off"></label>
<label class="ai-field" for="brand-description">설명 · 필수<textarea id="brand-description" required maxlength="1000" rows="5"></textarea></label>
<label class="ai-field" for="brand-url">URL · 선택<input id="brand-url" type="url" maxlength="2048" autocomplete="off" placeholder="https://example.com"></label>
<p class="ai-help">URL은 저장해 두는 참고용입니다. 추후 브랜드 설명을 고칠 때 확인할 수 있으며, 앱은 URL을 열거나 AI 프롬프트에 보내지 않습니다.</p>
<label class="ai-field" for="comment-min-chars">최소 글자 수 · 필수<input id="comment-min-chars" type="number" required min="1" max="1000" step="1" inputmode="numeric"></label>
<label class="ai-field" for="comment-max-chars">최대 글자 수 · 필수<input id="comment-max-chars" type="number" required min="1" max="1000" step="1" inputmode="numeric"></label>
<p class="ai-help">글자 수 설정이 없으면 기본 40~120자를 사용합니다. 1~1000자에서 최소값은 최대값보다 클 수 없습니다.</p>
<p id="brand-state" class="status" role="status" aria-live="polite"></p></div>
<div class="dialog-actions"><button id="brand-cancel" type="button" class="secondary">취소</button><button id="brand-save" type="button">댓글 생성 설정 저장</button></div>
</dialog>'''
    page = page.replace('<ol class="workflow"', brand_dialog + '<ol class="workflow"', 1)
    page = page.replace("</style>", ".ai-field textarea{display:block;width:100%;margin-top:6px;padding:9px;border:1px solid #8b9bb0;border-radius:8px;font:inherit;resize:vertical}</style>", 1)
    channel_script = """
const demoChannels=__DEMO_CHANNELS__;
const demoMode=__DEMO_MODE__;
const channelPattern=/^UC[A-Za-z0-9_-]{22}$/;
const channelErrors={SETTINGS_CHANNELS_INVALID:'채널은 5~20개여야 하며 ID가 중복되면 안 됩니다.',SETTINGS_CHANNEL_NAME_INVALID:'채널명은 비워두거나 1~100자로 입력하세요.',SETTINGS_CHANNEL_ID_INVALID:'채널 ID는 UC로 시작하는 24자리여야 합니다.',SETTINGS_TEST_CHANNEL_CONFLICT:'본인 테스트 영상의 채널은 중복 등록할 수 없습니다.',SETTINGS_WRITE_FAILED:'설정 파일을 저장하지 못했습니다.',RSS_CHANNEL_MISMATCH:'RSS가 다른 채널 ID를 반환했습니다.',RSS_INVALID_XML:'RSS 응답 형식이 올바르지 않습니다.',RSS_REDIRECT_BLOCKED:'RSS가 다른 주소로 이동해 연결을 차단했습니다.',CHANNEL_TEST_NETWORK_FAILED:'YouTube RSS에 연결하지 못했습니다.',CHANNEL_TEST_FAILED:'RSS 연결 확인에 실패했습니다.'};
let savedChannels=[],draftChannels=[],visibleRows=3,previousOverflow='';
const dialog=$('channel-dialog');
const optionsMenu=$('options-menu');
function closeOptions(){optionsMenu.hidden=true;$('options-open').setAttribute('aria-expanded','false');}
$('options-open').addEventListener('click',()=>{const opening=optionsMenu.hidden;optionsMenu.hidden=!opening;$('options-open').setAttribute('aria-expanded',String(opening));if(opening)$('channel-menu-open').focus();});
document.addEventListener('click',event=>{if(!optionsMenu.hidden&&!optionsMenu.contains(event.target)&&event.target!==$('options-open'))closeOptions();});
document.addEventListener('keydown',event=>{if(optionsMenu.hidden)return;if(event.key==='Escape'){event.preventDefault();closeOptions();$('options-open').focus();}if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();const items=[$('channel-menu-open'),$('profile-menu-open'),$('brand-menu-open'),$('ai-menu-open')];const offset=event.key==='ArrowDown'?1:-1;items[(items.indexOf(document.activeElement)+offset+items.length)%items.length].focus();}});
function channelMessage(message,bad=false){const state=$('channel-state');state.textContent=message;state.classList.toggle('error',bad);}
function rowValid(item){return channelPattern.test(item.channel_id?.trim()||'');}
function updateChannelSaveGuide(){const ids=draftChannels.map(item=>item.channel_id.trim());const valid=draftChannels.length>=5&&draftChannels.length<=20&&draftChannels.every(rowValid)&&new Set(ids).size===ids.length;guideButton($('channel-save'),demoMode?'연습 모드에서는 채널 설정을 저장할 수 없습니다.':valid?'':'채널 ID 5~20개를 중복 없이 입력해주세요.');}
async function testChannel(i,nameInput,idInput,state,test){
  const name=nameInput.value.trim(),id=idInput.value.trim();state.replaceChildren();state.className='row-state muted';
  if(!channelPattern.test(id)){state.textContent='채널 ID는 UC로 시작하는 24자리여야 합니다.';state.className='row-state error';return;}
  guideButton(test,'YouTube RSS를 확인하는 중입니다.');
  try{
    const data=await json(await fetch('/api/channels/test',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({channel_name:name,channel_id:id})}));
    const resolved=name||data.channel_name||'';if(!name&&resolved)nameInput.value=resolved;state.textContent='연결 확인 · '+(resolved||id)+' · 최근 항목 '+data.video_count+'개 (소유권 확인 아님)';draftChannels[i]={channel_name:resolved,channel_id:id};
  }catch(error){state.textContent=channelErrors[error.message]||'연결 실패: '+error.message;state.className='row-state error';}
  finally{guideButton(test,demoMode?'연습 모드에서는 연결 테스트를 할 수 없습니다.':'');updateChannelSaveGuide();}
}
function renderChannels(){
  const rows=$('channel-rows');rows.replaceChildren();$('channel-count').textContent='현재 '+savedChannels.length+'개 등록 · '+visibleRows+'개 표시';$('channel-add').hidden=visibleRows>=20;
  for(let i=0;i<visibleRows;i++){
    const item=draftChannels[i]||{channel_name:'',channel_id:''};const row=document.createElement('div');row.className='channel-row';
    const idLabel=document.createElement('label');idLabel.textContent=(i+1)+'번째 채널 ID (필수)';idLabel.htmlFor='channel-id-'+i;const idInput=document.createElement('input');idInput.id=idLabel.htmlFor;idInput.value=item.channel_id||'';idInput.maxLength=24;idInput.placeholder='UC로 시작하는 24자리';idInput.autocomplete='off';idInput.spellcheck=false;idInput.readOnly=demoMode;idLabel.append(idInput);
    const nameLabel=document.createElement('label');nameLabel.textContent='채널명 (선택)';nameLabel.htmlFor='channel-name-'+i;const nameInput=document.createElement('input');nameInput.id=nameLabel.htmlFor;nameInput.value=item.channel_name||'';nameInput.maxLength=100;nameInput.autocomplete='off';nameInput.placeholder='비워두면 연결 테스트에서 확인';nameInput.readOnly=demoMode;nameLabel.append(nameInput);
    const state=document.createElement('div');state.className='row-state muted';state.setAttribute('role','status');const test=document.createElement('button');test.type='button';test.className='secondary';test.textContent='연결 테스트';guideButton(test,demoMode?'연습 모드에서는 연결 테스트를 할 수 없습니다. 실제 대시보드를 열어주세요.':'');
    const changed=()=>{draftChannels[i]={channel_name:nameInput.value.trim(),channel_id:idInput.value.trim()};state.replaceChildren();updateChannelSaveGuide();};nameInput.addEventListener('input',changed);idInput.addEventListener('input',changed);test.addEventListener('click',()=>testChannel(i,nameInput,idInput,state,test));
    row.append(idLabel,nameLabel,test);if(i>=5){const remove=document.createElement('button');remove.type='button';remove.className='secondary';remove.textContent='행 삭제';guideButton(remove,demoMode?'연습 모드에서는 채널을 삭제할 수 없습니다.':'');remove.addEventListener('click',()=>{draftChannels.splice(i,1);visibleRows--;renderChannels();});row.append(remove);}row.append(state);rows.append(row);
  }updateChannelSaveGuide();
}
async function refreshChannels(){if(demoMode){savedChannels=demoChannels.map(item=>({...item}));return;}const result=await json(await fetch('/api/channels',{headers:{'X-Session-Token':token}}));if(!Array.isArray(result.entries))throw Error('CHANNEL_LIST_INVALID');savedChannels=result.entries.map(item=>({...item}));}
$('channel-menu-open').addEventListener('click',async()=>{closeOptions();previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.showModal();$('channel-title').focus();channelMessage('채널 설정을 불러오는 중입니다…');try{await refreshChannels();draftChannels=savedChannels.map(item=>({...item}));visibleRows=Math.max(3,draftChannels.length);renderChannels();channelMessage(demoMode?'연습 모드: 실제 저장과 연결 테스트를 하지 않습니다.':'채널명과 선택 채널 ID를 확인하세요.');}catch(error){channelMessage('채널 설정을 불러오지 못했습니다: '+error.message,true);}});
function closeChannels(){dialog.close();}$('channel-close').addEventListener('click',closeChannels);$('channel-cancel').addEventListener('click',closeChannels);dialog.addEventListener('close',()=>{document.body.style.overflow=previousOverflow;$('options-open').focus();});
$('channel-add').addEventListener('click',()=>{if(visibleRows>=20)return;if(visibleRows>=draftChannels.length)draftChannels.push({channel_name:'',channel_id:''});visibleRows++;renderChannels();$('channel-id-'+(visibleRows-1)).focus();});
$('channel-save').addEventListener('click',async()=>{const ids=draftChannels.map(item=>item.channel_id.trim());if(draftChannels.length<5||draftChannels.length>20||!draftChannels.every(rowValid)||new Set(ids).size!==ids.length){channelMessage('채널 ID 5~20개를 중복 없이 입력하세요.',true);return;}guideButton($('channel-save'),'채널 설정을 저장하는 중입니다.');channelMessage('채널 설정을 저장하는 중입니다…');try{const result=await json(await fetch('/api/channels',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({entries:draftChannels})}));savedChannels=result.entries.map(item=>({...item}));draftChannels=savedChannels.map(item=>({...item}));visibleRows=draftChannels.length;renderChannels();selected=null;ready=false;setStep('load');guideButton($('post'),'채널 설정이 바뀌었습니다. 영상을 다시 불러오고 초안을 승인해주세요.');$('videos').replaceChildren();$('selection').className='empty';$('selection').textContent='설정이 바뀌었습니다. 영상을 다시 불러오세요.';$('feed-state').textContent='채널 설정이 저장됐습니다. 영상을 다시 불러오세요.';$('post-state').textContent='승인된 초안을 다시 선택해야 합니다.';channelMessage('저장했습니다. 영상 목록을 다시 불러오세요.');}catch(error){channelMessage(channelErrors[error.message]||'저장 실패: '+error.message,true);}finally{updateChannelSaveGuide();}});
""".replace("__DEMO_CHANNELS__", json.dumps(
        [{"channel_name": name, "channel_id": channel_id} for channel_id, name in CHANNELS.items()],
        ensure_ascii=False)).replace(
        "__DEMO_MODE__", "true" if demo else "false")
    page = page.replace("</script>", channel_script + "</script>")
    ai_script = """
const aiDemo=__AI_DEMO__;
const aiPresets=__AI_PRESETS__;
const aiErrors={AI_PROVIDER_INVALID:'AI 제공사를 선택하세요.',AI_MODEL_INVALID:'제공사의 정확한 모델 ID를 입력하세요.',AI_KEY_INVALID:'API 키 형식을 확인하세요.',AI_KEY_MISSING:'선택한 AI 제공사의 API 키가 없습니다. 프로젝트 루트 .env 또는 AI API 관리에서 키를 설정하세요.',AI_AUTH_FAILED:'API 인증 또는 사용 권한을 확인하세요.',AI_MODEL_UNAVAILABLE:'모델 ID 또는 계정의 모델 접근 권한을 확인하세요.',AI_RATE_LIMITED:'AI 호출 한도에 도달했습니다.',AI_NETWORK_FAILED:'AI 서비스에 연결하지 못했습니다.',AI_REDIRECT_BLOCKED:'AI API 주소 이동을 차단했습니다.',AI_PROVIDER_FAILED:'AI 서비스 요청이 실패했습니다.',AI_EMPTY_RESPONSE:'AI가 빈 응답을 반환했습니다. 잠시 후 다시 시도하세요.',AI_RESPONSE_INVALID:'AI 응답의 JSON 형식을 확인할 수 없습니다.',AI_RESPONSE_TRUNCATED:'AI가 응답을 끝까지 만들기 전에 토큰 한도에 도달했습니다. 다시 시도하세요.',AI_RESPONSE_SCHEMA_INVALID:'AI 응답에 필요한 고민·근거·댓글 항목이 없습니다. 모델 설정을 확인하고 다시 시도하세요.',AI_RESPONSE_TOO_LARGE:'AI 응답이 너무 큽니다.',AI_TEST_FAILED:'AI 연결 테스트에 실패했습니다.',SETTINGS_WRITE_FAILED:'설정 파일을 저장하지 못했습니다.'};
let aiCurrent=null,aiDirty=false,aiPreviousOverflow='';
const aiDialog=$('ai-dialog');
async function checkAiDraftAvailability(button){
  if(aiDemo){guideButton(button,'연습 모드에서는 AI 초안을 만들 수 없습니다. 실제 대시보드를 열어주세요.');return;}
  try{const state=await json(await fetch('/api/ai',{headers:{'X-Session-Token':token}}));
    if(document.body.contains(button))guideButton(button,state.has_key?'':'우측 상단의 옵션 → AI API 관리에서 AI API 키를 입력해주세요.');
  }catch(_){if(document.body.contains(button))guideButton(button,'AI 설정을 확인하지 못했습니다. 페이지를 새로고침해주세요.');}
}
function aiMessage(message,bad=false){const state=$('ai-state');state.textContent=message;state.classList.toggle('error',bad);}
function aiModelValue(){return $('ai-model-choice').value==='custom'?$('ai-model-custom').value.trim():$('ai-model-choice').value;}
function aiPopulateModels(provider,model){
  const select=$('ai-model-choice');select.replaceChildren();
  for(const preset of aiPresets[provider]){const option=document.createElement('option');option.value=preset.id;option.textContent=preset.label+(preset.recommended?' · 추천':'');select.append(option);}
  const custom=document.createElement('option');custom.value='custom';custom.textContent='직접 입력…';select.append(custom);
  if(aiPresets[provider].some(preset=>preset.id===model)){select.value=model;$('ai-model-custom').value='';}
  else{select.value='custom';$('ai-model-custom').value=model;}
  $('ai-custom-wrap').hidden=select.value!=='custom';
}
function aiUpdateKeyStatus(){
  const same=aiCurrent&&$('ai-provider').value===aiCurrent.provider;
  if(!same){$('ai-key-status').textContent='제공사를 바꾸면 이전 제공사의 키는 재사용하지 않습니다.';return;}
  const source=aiCurrent.key_source;
  $('ai-key-status').textContent=source==='local'?'로컬 키가 설정되어 있습니다. 값은 표시하지 않습니다.':source==='environment'?'환경변수 키가 설정되어 있습니다. 값은 표시하지 않습니다.':'설정된 API 키가 없습니다.';
}
function aiMarkDirty(){aiDirty=true;guideButton($('ai-test'),'AI 설정을 저장한 뒤 연결 테스트를 눌러주세요.');const model=aiModelValue();const conflict=$('ai-clear-key').checked&&Boolean($('ai-key').value);guideButton($('ai-save'),aiDemo?'연습 모드에서는 AI 설정을 저장할 수 없습니다.':conflict?'새 키 입력과 저장된 키 삭제 중 하나만 선택해주세요.':/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(model)?'':'제공사의 정확한 모델 ID를 입력해주세요.');aiUpdateKeyStatus();aiMessage('변경 내용을 저장한 뒤 연결 테스트를 실행하세요.');}
async function aiRefresh(){
  aiCurrent=aiDemo?{provider:'openai',model:'gpt-5.4-mini',has_key:false,key_source:'none'}:
    await json(await fetch('/api/ai',{headers:{'X-Session-Token':token}}));
  $('ai-provider').value=aiCurrent.provider;aiPopulateModels(aiCurrent.provider,aiCurrent.model);
  $('ai-key').value='';$('ai-clear-key').checked=false;aiDirty=false;aiUpdateKeyStatus();
  guideButton($('ai-save'),aiDemo?'연습 모드에서는 AI 설정을 저장할 수 없습니다. 실제 대시보드를 열어주세요.':'');guideButton($('ai-test'),aiDemo?'연습 모드에서는 AI 연결 테스트를 할 수 없습니다.':!aiCurrent.has_key?'선택한 AI 제공사의 API 키를 입력하고 저장해주세요.':'');
  $('ai-key').disabled=aiDemo;$('ai-clear-key').disabled=aiDemo;
  aiMessage(aiDemo?'연습 모드: 설정 저장과 AI 외부 호출을 하지 않습니다.':'모델과 키를 확인한 뒤 저장하세요. 연결 테스트는 API 요청 한 건을 사용합니다.');
}
$('youtube-key-save').addEventListener('click',async()=>{const key=$('youtube-key').value.trim();if(!key){aiMessage('새 YouTube Data API 키를 입력하세요.',true);return;}try{await localPost('/api/youtube-key',{api_key:key});$('youtube-key').value='';aiMessage('YouTube 키를 저장했습니다. 다음 초안 생성부터 적용됩니다.');}catch(error){aiMessage('YouTube 키 저장 실패: '+error.message,true);}});
$('ai-menu-open').addEventListener('click',async()=>{
  closeOptions();aiPreviousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
  aiDialog.showModal();$('ai-title').focus();aiMessage('AI 설정을 불러오는 중입니다…');
  guideButton($('ai-save'),'AI 설정을 불러오는 중입니다. 잠시 기다려주세요.');guideButton($('ai-test'),'AI 설정을 불러오는 중입니다. 잠시 기다려주세요.');
  try{await aiRefresh();}catch(_){aiMessage('AI 설정을 불러오지 못했습니다.',true);guideButton($('ai-save'),'AI 설정을 불러오지 못했습니다. 대시보드를 새로고침해주세요.');guideButton($('ai-test'),'AI 설정을 불러오지 못했습니다. 대시보드를 새로고침해주세요.');}
});
function aiClose(){aiDialog.close();}
$('ai-close').addEventListener('click',aiClose);$('ai-cancel').addEventListener('click',aiClose);
aiDialog.addEventListener('close',()=>{$('ai-key').value='';document.body.style.overflow=aiPreviousOverflow;$('options-open').focus();});
$('ai-provider').addEventListener('change',()=>{const presets=aiPresets[$('ai-provider').value];aiPopulateModels($('ai-provider').value,(presets.find(preset=>preset.recommended)||presets[0]).id);aiMarkDirty();});
$('ai-model-choice').addEventListener('change',()=>{$('ai-custom-wrap').hidden=$('ai-model-choice').value!=='custom';aiMarkDirty();if(!$('ai-custom-wrap').hidden)$('ai-model-custom').focus();});
for(const id of ['ai-model-custom','ai-key','ai-clear-key'])$(''+id).addEventListener(id==='ai-clear-key'?'change':'input',aiMarkDirty);
$('ai-save').addEventListener('click',async()=>{
  if(aiDemo)return;
  const provider=$('ai-provider').value,model=aiModelValue(),apiKey=$('ai-key').value,clearKey=$('ai-clear-key').checked;
  if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(model)){aiMessage('제공사의 정확한 모델 ID를 입력하세요.',true);return;}
  if(clearKey&&apiKey){aiMessage('새 키 입력과 저장된 키 삭제를 함께 선택할 수 없습니다.',true);return;}
  guideButton($('ai-save'),'AI 설정을 저장하는 중입니다. 잠시 기다려주세요.');aiMessage('AI 설정을 저장하는 중입니다…');
  try{aiCurrent=await json(await fetch('/api/ai',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({provider,model,api_key:apiKey,clear_key:clearKey})}));
    $('ai-key').value='';$('ai-clear-key').checked=false;aiDirty=false;aiUpdateKeyStatus();
    guideButton($('ai-test'),aiCurrent.has_key?'':'선택한 AI 제공사의 API 키를 입력하고 저장해주세요.');aiMessage('저장했습니다. 연결 테스트는 직접 누를 때만 실행됩니다.');
  }catch(error){aiMessage(aiErrors[error.message]||'저장 실패: '+error.message,true);}
  finally{guideButton($('ai-save'),aiDemo?'연습 모드에서는 AI 설정을 저장할 수 없습니다.':'');}
});
$('ai-test').addEventListener('click',async()=>{
  if(aiDemo||aiDirty||!aiCurrent||!aiCurrent.has_key)return;
  guideButton($('ai-test'),'AI 연결을 확인하는 중입니다. 잠시 기다려주세요.');aiMessage('저장된 제공사와 모델로 AI 연결을 확인하는 중입니다…');
  try{const result=await json(await fetch('/api/ai/test',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:'{}'}));
    aiMessage('연결 확인: '+result.provider+' · '+result.model+' (초안·게시 승인과 무관)');
  }catch(error){aiMessage(aiErrors[error.message]||'연결 실패: '+error.message,true);if(error.message==='AI_AUTH_FAILED')showToast('AI API 키가 유효하지 않습니다. 우측 상단 옵션 → AI API 관리에서 키를 다시 입력해주세요.');}
  finally{guideButton($('ai-test'),aiDirty?'AI 설정을 저장한 뒤 연결 테스트를 눌러주세요.':!aiCurrent.has_key?'선택한 AI 제공사의 API 키를 입력하고 저장해주세요.':'');}
});
""".replace("__AI_DEMO__", "true" if demo else "false").replace(
        "__AI_PRESETS__", json.dumps(provider_presets, ensure_ascii=False))
    page = page.replace("</script>", ai_script + "</script>")
    brand_script = """
const brandDialog=$('brand-dialog');
let brandPreviousOverflow='';
function brandMessage(message,bad=false){const state=$('brand-state');state.textContent=message;state.classList.toggle('error',bad);}
function brandClose(){brandDialog.close();}
$('brand-menu-open').addEventListener('click',async()=>{
  closeOptions();brandPreviousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
  brandDialog.showModal();$('brand-title').focus();brandMessage('브랜드 설정을 불러오는 중입니다…');
  guideButton($('brand-save'),'설정을 불러오는 중입니다.');
  if(__BRAND_DEMO__){brandMessage('연습 모드에서는 브랜드 설정을 저장할 수 없습니다.');return;}
  try{const brand=await json(await fetch('/api/comment-settings',{headers:{'X-Session-Token':token}}));
    $('brand-name').value=brand.name;$('brand-description').value=brand.description;$('brand-url').value=brand.reference_url;
    $('comment-min-chars').value=brand.min_chars;$('comment-max-chars').value=brand.max_chars;
    guideButton($('brand-save'),'');brandMessage('브랜드 정보와 글자 수 범위를 확인한 뒤 저장하세요.');
  }catch(_){brandMessage('브랜드 설정을 불러오지 못했습니다.',true);guideButton($('brand-save'),'설정을 불러오지 못했습니다.');}
});
$('brand-close').addEventListener('click',brandClose);$('brand-cancel').addEventListener('click',brandClose);
brandDialog.addEventListener('close',()=>{document.body.style.overflow=brandPreviousOverflow;$('options-open').focus();});
$('brand-save').addEventListener('click',async()=>{
  const name=$('brand-name').value.trim(),description=$('brand-description').value.trim(),reference_url=$('brand-url').value.trim();
  const min_chars=Number($('comment-min-chars').value),max_chars=Number($('comment-max-chars').value);
  if(!name||!description){brandMessage('브랜드명과 설명을 모두 입력하세요.',true);return;}
  if(!Number.isInteger(min_chars)||!Number.isInteger(max_chars)||min_chars<1||max_chars>1000||min_chars>max_chars){brandMessage('글자 수는 1~1000자이고 최소값은 최대값 이하로 입력하세요.',true);return;}
  if(reference_url&&!$('brand-url').checkValidity()){brandMessage('URL은 http 또는 https 주소로 입력하세요.',true);return;}
  guideButton($('brand-save'),'저장하는 중입니다.');brandMessage('댓글 생성 설정을 저장하는 중입니다…');
  try{await localPost('/api/comment-settings',{name,description,reference_url,min_chars,max_chars});if(selected)await selectVideo(selected);brandMessage('저장했습니다. 다음 AI 초안 생성부터 적용됩니다. 브랜드명·설명·글자 수 변경 후 기존 초안은 다시 생성하고 승인해야 합니다.');}
  catch(error){const messages={BRAND_NAME_INVALID:'브랜드명은 1~80자로 입력하세요.',BRAND_DESCRIPTION_INVALID:'설명은 1~1000자로 입력하세요.',BRAND_URL_INVALID:'URL은 http 또는 https 주소로 입력하세요.',COMMENT_LENGTH_SETTINGS_INVALID:'글자 수는 1~1000자이고 최소값은 최대값 이하로 입력하세요.'};brandMessage(messages[error.message]||'저장 실패: '+error.message,true);}
  finally{guideButton($('brand-save'),'');}
});
""".replace("__BRAND_DEMO__", "true" if demo else "false")
    page = page.replace("</script>", brand_script + "</script>")
    page = page.replace("async function loadVideos(){", "async function loadVideos(){progressActive=false;")
    page = page.replace("if(!data.videos.length)line($('videos')", "videoStates=data.states||{};if(!data.videos.length)line($('videos')", 1)
    page = page.replace("async function selectVideo(id){", "async function selectVideo(id){progressActive=false;")
    profile_script = """
const profileDialog=$('profile-dialog');
function profileMessage(text,bad=false){const state=$('profile-state');state.textContent=text;state.classList.toggle('error',bad);}
let profileSelectedLabel='유튜브1',profileOptions=[],videoStates={};
async function refreshProfiles(){const data=await json(await fetch('/api/profile-options',{headers:{'X-Session-Token':token}}));profileSelectedLabel=data.selected;profileOptions=data.options||[];renderProfileChoices();return data;}
let loginWatch=null,loginWatchBusy=false;
function watchLoginWindow(label){if(loginWatch)clearInterval(loginWatch);loginWatch=setInterval(async()=>{if(loginWatchBusy)return;loginWatchBusy=true;try{const data=await refreshProfiles();const entry=data.options.find(item=>item.label===label);if(entry&&!entry.login_window_open){clearInterval(loginWatch);loginWatch=null;if(!$('post-continue').hidden)guideButton($('post-continue'));profileMessage(label+' 로그인 창을 닫았습니다. 현재 계정 확인을 눌러 로그인 결과를 확인하세요.');}}catch(error){profileMessage('로그인 창 상태 확인 실패: '+explainReason(error.message),true);}finally{loginWatchBusy=false;}},2000);}
function renderProfileChoices(){const list=$('profile-list');list.replaceChildren();const activeWindow=profileOptions.find(item=>item.login_window_open);for(const entry of profileOptions){const row=document.createElement('div');row.className='profile-row';row.setAttribute('role','listitem');const info=document.createElement('div');info.className='profile-info';const heading=document.createElement('div');heading.className='profile-heading';const name=document.createElement('strong');name.textContent=entry.label;const email=document.createElement('span');email.className='profile-email';email.textContent=entry.account_state==='SIGNED_IN'?(entry.verified_email||'로그인 확인 · 로그인됨'):'계정 확인 필요';heading.append(name,email);const status=document.createElement('span');status.textContent=entry.login_window_open?'로그인 창 열림':entry.account_state==='SIGNED_IN'?'로그인됨 · '+new Date(entry.verified_at).toLocaleString('ko-KR'):entry.account_state==='SIGNED_OUT'?'로그아웃 확인됨':entry.configured?'로그인 상태 미확인':'전용 프로필 준비 필요';info.append(heading,status);const busyReason=activeWindow?activeWindow.label+' Chrome 창이 열려 있습니다. 그 창을 닫은 뒤 다시 눌러주세요.':'';const verify=document.createElement('button');verify.type='button';verify.textContent=entry.account_state==='SIGNED_OUT'?'로그인하기':'현재 계정 확인';guideButton(verify,busyReason);verify.addEventListener('click',()=>entry.account_state==='SIGNED_OUT'?openAppProfile(entry.label):checkProfileAccount(entry.label));row.append(info,verify);if(entry.account_state==='SIGNED_IN'){const change=document.createElement('button');change.type='button';change.className='secondary profile-change';change.textContent='계정 변경';guideButton(change,busyReason);change.addEventListener('click',()=>openAppProfile(entry.label));heading.append(change);}list.append(row);}guideButton($('profile-setup'),activeWindow?activeWindow.label+' Chrome 창을 닫은 뒤 새 프로필을 추가해주세요.':profileOptions.length>=20?'프로필은 최대 20개까지 등록할 수 있습니다.':'');}
async function openAppProfile(label){profileMessage(label+'의 로그인용 영상 페이지를 여는 중입니다…');try{const result=await localPost('/api/profile/setup',{label});videoStates=result.states||videoStates;await refreshProfiles();watchLoginWindow(label);profileMessage(label+' 전용 Chrome에서 계정을 선택하거나 추가하세요. 창을 닫은 뒤 현재 계정 확인을 눌러주세요.');}catch(error){const message='로그인 창을 열지 못했습니다: '+explainReason(error.message);profileMessage(message,true);showToast(message);}}
async function checkProfileAccount(label){profileMessage(label+'의 우리 채널 영상 페이지에서 로그인 상태를 확인하는 중입니다…');try{const data=await localPost('/api/profile/verify-email',{label});profileOptions=data.options||profileOptions;renderProfileChoices();const entry=profileOptions.find(item=>item.label===label);profileMessage(label+' 로그인 확인 완료 · '+(entry?.verified_email||'계정'));}catch(error){if(['PROFILE_SIGNED_OUT','PROFILE_NOT_CONFIGURED','PROFILE_DIRECTORY_MISSING'].includes(error.message)){profileMessage(label+'은 로그인이 필요합니다. 로그인 창을 엽니다. 영상 페이지 오른쪽 위 “로그인”은 직접 눌러주세요.');await openAppProfile(label);return;}const message=error.message==='PROFILE_ACCOUNT_UNKNOWN'?'로그인 여부를 정확히 확인하지 못했습니다. 네트워크와 영상 페이지를 확인한 뒤 다시 시도하세요.':'계정 확인 실패: '+explainReason(error.message);profileMessage(message,true);showToast(message);}}
async function openProfileDialog(){
  profileDialog.showModal();$('profile-title').focus();profileMessage('현재 연결을 불러오는 중입니다…');
  try{await refreshProfiles();profileMessage('프로필별 현재 계정을 확인할 수 있습니다.');}
  catch(_){profileMessage('프로필 목록을 불러오지 못했습니다.',true);}
}
function createProfileButton(panel){const action=document.createElement('button');action.type='button';action.textContent='앱 전용 프로필 확인';action.addEventListener('click',openProfileDialog);panel.append(action);}
$('profile-menu-open').addEventListener('click',()=>{closeOptions();openProfileDialog();});
$('profile-setup').addEventListener('click',()=>{$('profile-add-form').hidden=false;$('profile-add-name').value='';$('profile-add-name').focus();profileMessage('새 프로필 이름을 입력하세요.');});
$('profile-add-cancel').addEventListener('click',()=>{$('profile-add-form').hidden=true;$('profile-setup').focus();});
$('profile-add-save').addEventListener('click',async()=>{const label=$('profile-add-name').value.trim();if(!label){profileMessage('프로필 이름을 입력하세요.',true);return;}if(profileOptions.some(item=>item.label.toLocaleLowerCase('ko-KR')===label.toLocaleLowerCase('ko-KR'))){profileMessage('이미 사용 중인 프로필 이름입니다.',true);return;}guideButton($('profile-add-save'),'프로필을 준비하는 중입니다.');try{await localPost('/api/profile/add',{label});$('profile-add-form').hidden=true;await refreshProfiles();profileMessage(label+' 프로필을 만들었습니다. 로그인 창을 엽니다. 영상 페이지 오른쪽 위 “로그인”은 직접 눌러주세요.');await openAppProfile(label);}catch(error){const messages={PROFILE_NAME_DUPLICATE:'이미 사용 중인 프로필 이름입니다.',PROFILE_NAME_INVALID:'프로필 이름은 1~30자로 입력하고 경로 문자는 제외하세요.',PROFILE_LIMIT_REACHED:'프로필은 최대 20개까지 등록할 수 있습니다.'};profileMessage(messages[error.message]||'프로필 추가 실패: '+explainReason(error.message),true);}finally{guideButton($('profile-add-save'),'');}});
$('profile-cancel').addEventListener('click',()=>profileDialog.close());
profileDialog.addEventListener('close',()=>{if(selected)$('selection').focus?.();});
async function openLoginAfterPost(){progressActive=false;try{await refreshProfiles();const label=videoStates[selected]?.profile||profileSelectedLabel;await localPost('/api/profile/setup',{label});guideButton($('post-continue'),'열린 영상 페이지 오른쪽 위 “로그인”으로 로그인하고 창을 닫은 뒤 댓글 계속하기를 눌러주세요.');watchLoginWindow(label);$('post-state').textContent='로그인이 필요합니다. 열린 전용 Chrome에서 계정을 선택하고 창을 닫은 뒤 댓글 계속하기를 누르세요.';$('post-continue').hidden=false;}catch(error){$('post-state').textContent='로그인 창을 열지 못했습니다: '+explainReason(error.message);guideButton($('post-continue'),'로그인 창을 다시 열어 “로그인”을 누른 뒤 계속해주세요.');$('post-continue').hidden=false;}}
$('post-continue').addEventListener('click',async()=>{if(!selected)return;$('post-continue').hidden=true;const videoId=selected;await selectVideo(videoId);if(ready)await postComment();else $('post-continue').hidden=false;});
refreshProfiles().catch(()=>{});
"""
    page = page.replace("</script>", profile_script + "</script>")
    progress = """
let progressActive=false;
$('post-state').setAttribute('aria-live','polite');
const progressLabels={profile_check:'프로필 확인',opening:'브라우저 실행',navigating:'YouTube 탐색',checking_login:'로그인 상태 확인',comment_window:'댓글 입력창 확인',typing:'댓글 입력',submitting:'게시',verifying:'게시 결과 확인',posted:'완료 · 댓글 보기',failed:'게시 실패'};
$('post').addEventListener('click',()=>{progressActive=true;$('capture').replaceChildren();});
async function updateProgress(){
  if(!progressActive)return;
  try {
    const response=await fetch('/api/progress',{headers:{'X-Session-Token':token}});
    if(!response.ok)return;
    const data=await response.json();
    if(!data.events.length)return;
    const last=data.events[data.events.length-1];
    $('post-state').textContent=[progressLabels[last.stage]||last.stage,last.reason_code].filter(Boolean).join(' · ');
    if(last.screenshot_url){
      await loadCapture(last.screenshot_url);
    }
  } catch (_) {}
}
setInterval(updateProgress,500);
"""
    return page.replace("</script>", progress + "</script>").encode("utf-8")
