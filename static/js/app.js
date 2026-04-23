/* ═══════════════════════════════════════════════════════════════════════════
   Grocery Shopping Optimizer — Frontend Application
   ═══════════════════════════════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────────────────────────────────
const S = {
  basket: JSON.parse(localStorage.getItem('basket') || '[]'),
  mealPlan: JSON.parse(localStorage.getItem('mealPlan') || 'null'),
  shoppingList: JSON.parse(localStorage.getItem('shoppingList') || '[]'),
  history: JSON.parse(localStorage.getItem('history') || '[]'),
  chat: JSON.parse(localStorage.getItem('chatMessages') || '[]'),
  settings: JSON.parse(localStorage.getItem('settings') || '{}'),
  config: null,
  plannerStep: 0,
};

function save(key) {
  const map = { basket: S.basket, mealPlan: S.mealPlan, shoppingList: S.shoppingList, history: S.history, chatMessages: S.chat, settings: S.settings };
  if (map[key] !== undefined) localStorage.setItem(key, JSON.stringify(map[key]));
}

// ── API ──────────────────────────────────────────────────────────────────────
const api = {
  async post(url, body) {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return r.json();
  },
  async get(url) { return (await fetch(url)).json(); },
};

// ── Toast ────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = { success: 'fa-circle-check', error: 'fa-circle-xmark', info: 'fa-circle-info' };
  el.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i> ${msg}`;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(100%)'; setTimeout(() => el.remove(), 300); }, 3500);
}

// ── Badge ────────────────────────────────────────────────────────────────────
function updateBadge() {
  const b = document.getElementById('basket-badge');
  if (!b) return;
  if (S.basket.length) { b.style.display = ''; b.textContent = S.basket.length; }
  else { b.style.display = 'none'; }
}

// ── Basket helpers ───────────────────────────────────────────────────────────
function addToBasket(item) {
  S.basket.push({ name: item.name || '', price: parseFloat(item.price) || 0, qty: item.qty || '1 unit', url: item.url || '', count: parseInt(item.count) || 1 });
  save('basket'); updateBadge();
  toast(`Added ${item.name} to basket`, 'success');
}

// ── Router ───────────────────────────────────────────────────────────────────
const pages = { '': renderDashboard, 'planner': renderPlanner, 'basket': renderBasket, 'calendar': renderCalendar, 'recipes': renderRecipes, 'history': renderHistory, 'fridge': renderFridge, 'body': renderBody };

function route() {
  const hash = location.hash.replace('#/', '') || '';
  const page = hash.split('?')[0];
  const fn = pages[page] || renderDashboard;

  // Update nav
  document.querySelectorAll('.nav-links a').forEach(a => {
    a.classList.toggle('active', (a.dataset.page || 'dashboard') === (page || 'dashboard'));
  });

  // Update title
  const titles = { '': 'Dashboard', planner: 'Meal Planner', basket: 'Basket', calendar: 'Calendar', recipes: 'Recipes', history: 'History', nutrition: 'Nutrition Coach', fridge: "What's in My Fridge?", body: 'Body Optimizer' };
  document.getElementById('page-title').textContent = titles[page] || 'Dashboard';

  const content = document.getElementById('content');
  content.innerHTML = '';
  content.className = 'page-enter';
  fn(content);
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGES
// ══════════════════════════════════════════════════════════════════════════════

// ── Dashboard ────────────────────────────────────────────────────────────────
function renderDashboard(el) {
  const plan = S.mealPlan || [];
  const basket = S.basket || [];
  const totalCost = basket.reduce((s,i) => s + (parseFloat(i.price)||0)*(i.count||1), 0);
  const totalCal  = plan.length ? Math.round(plan.reduce((s,m)=>s+(+m.calories||0),0) / Math.max(1,[...new Set(plan.map(m=>m.Day))].length)) : 0;

  el.innerHTML = `
    <div class="hero-greeting">
      <div class="hero-text">
        <div class="greeting-sub">Good morning,</div>
        <h2>Ready to eat well today?</h2>
        <p>${plan.length ? `Your ${[...new Set(plan.map(m=>m.Day))].length}-day meal plan is active. Basket has ${basket.length} item${basket.length!==1?'s':''}.` : 'Generate a meal plan to get started with your personalised grocery list.'}</p>
        <div class="hero-actions">
          <button class="btn btn-primary" onclick="location.hash='#/planner'"><i class="fa-solid fa-wand-magic-sparkles"></i> Meal Planner</button>
          <button class="btn btn-ghost" style="border-color:rgba(255,255,255,.3);color:rgba(255,255,255,.8)" onclick="location.hash='#/basket'"><i class="fa-solid fa-basket-shopping"></i> My Basket</button>
        </div>
      </div>
      <div class="hero-visual">🥗</div>
    </div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-icon ci-green"><i class="fa-solid fa-utensils"></i></div>
        <div class="kpi-text"><h4>Meals Planned</h4><div class="kpi-val">${plan.length}</div><div class="kpi-trend">${plan.length ? [...new Set(plan.map(m=>m.Day))].length+'-day plan' : 'No plan yet'}</div></div>
      </div>
      <div class="kpi">
        <div class="kpi-icon ci-amber"><i class="fa-solid fa-basket-shopping"></i></div>
        <div class="kpi-text"><h4>Basket Items</h4><div class="kpi-val">${basket.length}</div><div class="kpi-trend">${basket.length ? '€'+totalCost.toFixed(2)+' estimated' : 'Empty basket'}</div></div>
      </div>
      <div class="kpi">
        <div class="kpi-icon ci-blue"><i class="fa-solid fa-fire"></i></div>
        <div class="kpi-text"><h4>Avg Calories</h4><div class="kpi-val">${totalCal || '—'}</div><div class="kpi-trend">${totalCal ? 'per day' : 'Generate plan first'}</div></div>
      </div>
      <div class="kpi">
        <div class="kpi-icon ci-teal"><i class="fa-solid fa-euro-sign"></i></div>
        <div class="kpi-text"><h4>Basket Total</h4><div class="kpi-val">${basket.length ? '€'+totalCost.toFixed(2) : '€0'}</div><div class="kpi-trend">${basket.length ? basket.length+' items' : 'Add items'}</div></div>
      </div>
    </div>

    <div class="card-grid-3">
      <div class="quick-card" onclick="location.hash='#/planner'">
        <div class="quick-card-icon ci-green"><i class="fa-solid fa-wand-magic-sparkles" style="color:#fff"></i></div>
        <h4>Generate Meal Plan</h4>
        <p>AI-optimized plan based on your macros, budget, and preferences.</p>
        <div class="quick-card-arrow"><i class="fa-solid fa-arrow-right"></i> Start planner</div>
      </div>
      <div class="quick-card" onclick="location.hash='#/recipes'">
        <div class="quick-card-icon ci-amber"><i class="fa-solid fa-book-open" style="color:#fff"></i></div>
        <h4>Browse Recipes</h4>
        <p>Explore thousands of recipes from the Mercadona database, filterable by macro goals.</p>
        <div class="quick-card-arrow"><i class="fa-solid fa-arrow-right"></i> View recipes</div>
      </div>
      <div class="quick-card" onclick="location.hash='#/fridge'">
        <div class="quick-card-icon ci-teal"><i class="fa-solid fa-refrigerator" style="color:#fff"></i></div>
        <h4>What's in My Fridge?</h4>
        <p>Tell the AI what you have and it'll suggest recipes with zero waste.</p>
        <div class="quick-card-arrow"><i class="fa-solid fa-arrow-right"></i> Check fridge</div>
      </div>
    </div>

    <div class="card mt-3">
      <div class="card-header"><i class="fa-solid fa-chart-bar"></i><h3>Meal Plan Analytics</h3></div>
      <iframe id="dash-overview" src="/dash/overview" style="width:100%;height:580px;border:none;border-radius:6px" loading="lazy"></iframe>
    </div>
  `;
}

// ── Meal Planner ─────────────────────────────────────────────────────────────
function renderPlanner(el) {
  const step = S.plannerStep;
  el.innerHTML = `
    <div class="steps">
      <div class="step ${step > 0 ? 'done' : step === 0 ? 'active' : ''}"><div class="step-label">Configure</div></div>
      <div class="step ${step > 1 ? 'done' : step === 1 ? 'active' : ''}"><div class="step-label">Generate</div></div>
      <div class="step ${step > 2 ? 'done' : step === 2 ? 'active' : ''}"><div class="step-label">Review</div></div>
      <div class="step ${step > 3 ? 'done' : step === 3 ? 'active' : ''}"><div class="step-label">Shop</div></div>
    </div>
    <div id="planner-content"></div>
  `;
  const c = document.getElementById('planner-content');
  if (step === 0) renderPlannerConfig(c);
  else if (step === 1) renderPlannerGenerating(c);
  else if (step === 2) renderPlannerReview(c);
  else if (step === 3) renderPlannerShop(c);
}

function renderPlannerConfig(el) {
  const cuisines = S.config?.cuisine_map ? Object.keys(S.config.cuisine_map) : ['American','Italian','Mexican/Latin','Asian','Mediterranean','Healthy','Junk Food'];
  el.innerHTML = `
    <div class="card">
      <div class="card-header"><i class="fa-solid fa-sliders"></i><h3>Nutritional Targets & Preferences</h3></div>
      <div class="form-row">
        <div class="form-group"><label>Daily Calories</label><input type="number" id="p-cal" value="2000" min="800" max="5000"></div>
        <div class="form-group"><label>Protein (g)</label><input type="number" id="p-prot" value="100" min="20" max="400"></div>
        <div class="form-group"><label>Carbs (g)</label><input type="number" id="p-carb" value="250" min="20" max="600"></div>
        <div class="form-group"><label>Fat (g)</label><input type="number" id="p-fat" value="65" min="10" max="200"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Budget (&euro;/day)</label><input type="number" id="p-budget" value="50" min="5" max="200" step="5"></div>
        <div class="form-group"><label>Max Cook Time (min)</label><input type="number" id="p-time" value="60" min="10" max="180" step="5"></div>
        <div class="form-group"><label>Number of Days</label><input type="number" id="p-days" value="7" min="1" max="14"></div>
        <div class="form-group"><label>People</label><input type="number" id="p-people" value="1" min="1" max="10"></div>
      </div>
      <div class="form-group">
        <label>Meal Variability</label>
        <select id="p-var">
          <option value="High">High (unique meals each day)</option>
          <option value="Medium">Medium (repeat every 2 days)</option>
          <option value="Low">Low (batch cooking)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Meal Slots</label>
        <div class="chip-group" id="slot-chips">
          ${['Breakfast','Lunch','Snack','Dinner','Dessert','Beverage'].map(s =>
            `<div class="chip ${['Breakfast','Lunch','Snack','Dinner'].includes(s)?'selected':''}" data-slot="${s}">${s}</div>`
          ).join('')}
        </div>
      </div>
      <div class="form-group">
        <label>Cuisine Preferences</label>
        <div class="chip-group" id="cuisine-chips">
          ${cuisines.map(c => `<div class="chip" data-cuisine="${c}">${c}</div>`).join('')}
        </div>
      </div>
      <div class="form-group">
        <label>Dislikes <span class="hint">(comma-separated ingredients to exclude)</span></label>
        <input type="text" id="p-dislikes" placeholder="e.g. mushrooms, shrimp, tofu">
      </div>
      <div class="mt-2">
        <button class="btn-primary" onclick="startGeneration()"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate Meal Plan</button>
      </div>
    </div>
  `;

  // Chip toggle logic
  el.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => chip.classList.toggle('selected'));
  });
}

async function startGeneration() {
  const slots = [...document.querySelectorAll('#slot-chips .chip.selected')].map(c => c.dataset.slot);
  const cuisines = [...document.querySelectorAll('#cuisine-chips .chip.selected')].map(c => c.dataset.cuisine);
  if (!slots.length) { toast('Select at least one meal slot', 'error'); return; }

  // ⚠️ Read ALL form values BEFORE re-rendering (renderPlanner resets the DOM)
  const body = {
    calories: +document.getElementById('p-cal')?.value || 2000,
    protein: +document.getElementById('p-prot')?.value || 100,
    carbs: +document.getElementById('p-carb')?.value || 250,
    fat: +document.getElementById('p-fat')?.value || 65,
    budget: +document.getElementById('p-budget')?.value || 50,
    max_time: +document.getElementById('p-time')?.value || 60,
    days: +document.getElementById('p-days')?.value || 7,
    people: +document.getElementById('p-people')?.value || 1,
    variability: document.getElementById('p-var')?.value || 'High',
    slots, cuisines,
    dislikes: document.getElementById('p-dislikes')?.value || '',
  };

  // Cache form values BEFORE re-rendering so loading screen reads correct values
  S._planParams = body;

  // Now safe to re-render to the loading step
  S.plannerStep = 1;
  renderPlanner(document.getElementById('content'));

  try {
    const res = await api.post('/api/meal-plan/generate', body);
    if (res.ok) {
      S.mealPlan = res.meal_plan;
      S._nutrition = res.nutrition;
      save('mealPlan');
      S.plannerStep = 2;
      toast('Meal plan generated!', 'success');
    } else {
      S.plannerStep = 0;
      toast(res.error || 'Failed to generate plan', 'error');
    }
  } catch (e) {
    S.plannerStep = 0;
    toast('Network error: ' + e.message, 'error');
  }
  renderPlanner(document.getElementById('content'));
}

// ── Grocery Loader ──────────────────────────────────────────────────────────
const _GL_G='#1e7e2f',_GL_A='#f5a623',_GL_L='#5cb840';
const _GL_ICONS=[
  [c=>`<svg viewBox="0 0 48 48" fill="none"><path d="M4 6h6l1 5M11 11h28l-4.5 20H15.5L11 11z" stroke="${c}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="18.5" cy="39" r="3.5" fill="${c}"/><circle cx="33.5" cy="39" r="3.5" fill="${c}"/><path d="M15 29h22" stroke="${c}" stroke-width="2.5" stroke-linecap="round"/></svg>`,_GL_A],
  [c=>`<svg viewBox="0 0 48 48" fill="none"><path d="M12 15h24l3 28H9L12 15z" stroke="${c}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M17 15V10a7 7 0 0 1 14 0v5" stroke="${c}" stroke-width="3.2" stroke-linecap="round"/><path d="M17 24h14" stroke="${c}" stroke-width="2.8" stroke-linecap="round"/></svg>`,_GL_G],
  [c=>`<svg viewBox="0 0 48 48" fill="none"><path d="M13 21l5-12M35 21l-5-12M5 21h38l-4.5 20H9.5L5 21z" stroke="${c}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M18 21l2.5 13M24 21v13M30 21l-2.5 13" stroke="${c}" stroke-width="2.4" stroke-linecap="round"/></svg>`,_GL_L],
  [c=>`<svg viewBox="0 0 48 48" fill="none"><path d="M7 23C7 15 13 9 24 9s17 6 17 14v18H7V23z" stroke="${c}" stroke-width="3.2" stroke-linejoin="round"/><path d="M7 23h34" stroke="${c}" stroke-width="2.8" stroke-linecap="round"/><path d="M15 23v10M24 23v10M33 23v10" stroke="${c}" stroke-width="2.2" stroke-linecap="round" opacity=".5"/></svg>`,_GL_A],
];
function mountGroceryLoader(container){
  const uid=Date.now();
  container.innerHTML=`<div class="grocery-loader-wrap">
    <div class="gl-ring gl-ring-1"></div><div class="gl-ring gl-ring-2"></div>
    <div class="gl-ring gl-ring-3"></div><div class="gl-ring gl-ring-4"></div>
    <div class="gl-dot-orbit" id="gl-dot-orbit-${uid}"></div>
    <div class="gl-center"><div class="gl-slot" id="gl-sa-${uid}"></div><div class="gl-slot" id="gl-sb-${uid}"></div></div>
  </div>`;
  const dotEl=container.querySelector(`#gl-dot-orbit-${uid}`);
  [[_GL_G,0],[_GL_A,90],[_GL_L,180],[_GL_G,270]].forEach(([col,deg])=>{
    const rad=(deg-90)*Math.PI/180,r=95,x=97+r*Math.cos(rad)-3.5,y=97+r*Math.sin(rad)-3.5;
    const d=document.createElement('div');d.className='gl-dot';d.style.cssText=`background:${col};left:${x}px;top:${y}px`;dotEl.appendChild(d);
  });
  const sA=container.querySelector(`#gl-sa-${uid}`),sB=container.querySelector(`#gl-sb-${uid}`);
  function rdr(slot,idx){const[fn,col]=_GL_ICONS[idx];slot.innerHTML=fn(col);const s=slot.querySelector('svg');s.style.cssText='width:68px;height:68px;transition:opacity .25s ease,transform .25s ease';return s;}
  let cur=0,active=sA,inactive=sB;
  rdr(sA,0).style.cssText+='opacity:1;transform:scale(1)';
  rdr(sB,1).style.cssText+='opacity:0;transform:scale(.65)';
  setInterval(()=>{
    cur=(cur+1)%_GL_ICONS.length;
    const as=active.querySelector('svg');as.style.opacity='0';as.style.transform='scale(1.3)';
    const is=rdr(inactive,cur);is.style.opacity='0';is.style.transform='scale(.65)';
    setTimeout(()=>{is.style.opacity='1';is.style.transform='scale(1)';[active,inactive]=[inactive,active];rdr(inactive,(cur+1)%_GL_ICONS.length).style.cssText='width:68px;height:68px;opacity:0;transform:scale(.65)';},220);
  },1200);
}

function renderPlannerGenerating(el) {
  const daysCount = S._planParams?.days || 7;
  el.innerHTML = `<div class="loader-overlay">
  <div id="grocery-loader-mount"></div>
  <p>Optimising your meal plan…</p>
  <small>Matching ingredients to Mercadona's catalogue via AI</small>
  <div style="display:flex;gap:20px;margin-top:-8px">
    <div style="text-align:center"><div style="font-size:1.4rem;font-weight:700;color:var(--g600);font-family:var(--font-d)" id="gl-count-up">0</div><div style="font-size:.72rem;color:var(--text3)">Recipes scored</div></div>
    <div style="text-align:center"><div style="font-size:1.4rem;font-weight:700;color:var(--amber);font-family:var(--font-d)" id="gl-days-count">${daysCount}</div><div style="font-size:.72rem;color:var(--text3)">Days planned</div></div>
  </div>
</div>`;
  mountGroceryLoader(document.getElementById('grocery-loader-mount'));
  // Animate recipe counter
  let count = 0;
  const target = Math.round((daysCount || 7) * 14);
  const counterEl = document.getElementById('gl-count-up');
  if (counterEl) {
    const tick = setInterval(() => {
      count = Math.min(count + Math.ceil(target / 60), target);
      counterEl.textContent = count;
      if (count >= target) clearInterval(tick);
    }, 80);
  }
}

function renderPlannerReview(el) {
  if (!S.mealPlan || !S.mealPlan.length) { S.plannerStep = 0; renderPlanner(document.getElementById('content')); return; }

  const days = [...new Set(S.mealPlan.map(m => m.Day))];
  const nutr = S._nutrition || {};

  el.innerHTML = `
    <div class="flex-between mb-3">
      <div class="btn-group">
        <button class="btn-secondary" onclick="S.plannerStep=0;renderPlanner(document.getElementById('content'))"><i class="fa-solid fa-arrow-left"></i> Back</button>
        <button class="btn-primary" onclick="generateShoppingList()"><i class="fa-solid fa-cart-shopping"></i> Generate Shopping List</button>
      </div>
    </div>

    ${nutr.calories ? `
    <div class="kpi-grid mb-3">
      <div class="kpi"><div class="kpi-icon green"><i class="fa-solid fa-fire"></i></div><div class="kpi-text"><h4>Calories/Day</h4><div class="kpi-value">${Math.round(nutr.calories)}</div></div></div>
      <div class="kpi"><div class="kpi-icon blue"><i class="fa-solid fa-dumbbell"></i></div><div class="kpi-text"><h4>Protein</h4><div class="kpi-value">${Math.round(nutr.protein)}g</div></div></div>
      <div class="kpi"><div class="kpi-icon amber"><i class="fa-solid fa-wheat-awn"></i></div><div class="kpi-text"><h4>Carbs</h4><div class="kpi-value">${Math.round(nutr.carbs)}g</div></div></div>
      <div class="kpi"><div class="kpi-icon red"><i class="fa-solid fa-droplet"></i></div><div class="kpi-text"><h4>Fat</h4><div class="kpi-value">${Math.round(nutr.fat)}g</div></div></div>
    </div>` : ''}

    <div style="margin-bottom:20px">
      <h3 style="font-size:.9rem;font-weight:600;margin-bottom:8px"><i class="fa-solid fa-chart-bar"></i> Nutrition Analytics</h3>
      <iframe id="dash-meal-plan" src="/dash/meal-plan?t=${Date.now()}" style="width:100%;height:560px;border:none;border-radius:6px" loading="lazy"></iframe>
    </div>

    <div id="meal-plan-days">
      ${(() => {
        let globalIdx = 0;
        return days.map(day => {
          const meals = S.mealPlan.filter(m => m.Day === day);
          return `<div class="meal-day-group">
            <h4>${day}</h4>
            ${meals.map(m => {
              const idx = S.mealPlan.indexOf(m);
              return `
              <div class="meal-card" data-slot="${m.Meal || ''}" data-idx="${idx}" id="meal-card-${idx}" onclick="openMealModal(${idx})" title="Click for full recipe details">
                <div class="meal-card-header">
                  <div class="meal-slot">${m.Meal || ''}</div>
                  <div class="meal-actions" style="display:flex;flex-direction:column;align-items:center;gap:2px">
                    <span id="rating-badge-${idx}" style="font-size:.65rem;font-weight:700;color:var(--primary);min-height:14px;text-align:center"></span>
                    <div style="display:flex;gap:4px">
                      <button class="btn-icon" title="Rate up (+0.25)" onclick="event.stopPropagation();rateRecipe('${esc(m.name)}', 0.25, ${idx})"><i class="fa-solid fa-thumbs-up"></i></button>
                      <button class="btn-icon" title="Rate down (−0.25)" onclick="event.stopPropagation();rateRecipe('${esc(m.name)}', -0.25, ${idx})"><i class="fa-solid fa-thumbs-down"></i></button>
                      <button class="btn-icon swap-btn" title="Swap meal" onclick="event.stopPropagation();toggleSwapPanel(${idx})"><i class="fa-solid fa-right-left"></i></button>
                    </div>
                  </div>
                </div>
                <div class="meal-name">${m.name || 'Unknown'}</div>
                <div class="meal-macros">
                  <div class="macro-item">
                    <span class="macro-label"><i class="fa-solid fa-fire"></i> Calories</span>
                    <span class="macro-val">${Math.round(m.calories || 0)} kcal</span>
                  </div>
                  <div class="macro-item">
                    <span class="macro-label"><i class="fa-solid fa-dumbbell"></i> Protein</span>
                    <span class="macro-val">${Math.round(m.protein || 0)}g</span>
                  </div>
                  <div class="macro-item">
                    <span class="macro-label">Carbs</span>
                    <span class="macro-val">${Math.round(m.carbs || 0)}g</span>
                  </div>
                  <div class="macro-item">
                    <span class="macro-label">Fat</span>
                    <span class="macro-val">${Math.round(m.fat || 0)}g</span>
                  </div>
                </div>
                <div class="swap-panel" id="swap-panel-${idx}" style="display:none" onclick="event.stopPropagation()">
                  <div class="swap-panel-inner">
                    <div class="swap-section-label"><i class="fa-solid fa-wand-magic-sparkles"></i> Similar options</div>
                    <div class="swap-suggestions" id="swap-sugg-${idx}">
                      <div class="swap-loading"><i class="fa-solid fa-spinner fa-spin"></i> Loading…</div>
                    </div>
                    <div class="swap-section-label" style="margin-top:10px"><i class="fa-solid fa-keyboard"></i> Search by name</div>
                    <div class="swap-search-row">
                      <input class="swap-search-input" id="swap-search-${idx}" type="text" placeholder="Type a recipe name…"
                        oninput="onSwapSearch(${idx}, this.value)"
                        onkeydown="if(event.key==='Escape')closeSwapPanel(${idx})">
                    </div>
                    <div class="swap-suggestions" id="swap-search-results-${idx}"></div>
                  </div>
                </div>
              </div>`;
            }).join('')}
          </div>`;
        }).join('');
      })()}
    </div>
  `;
  // Load adjustments so badges show correct values immediately
  loadRatingAdjustments();
}

function esc(s) { return (s || '').replace(/'/g, "\\'").replace(/"/g, '&quot;'); }

// ── Meal detail modal ─────────────────────────────────────────────────────────
function openMealModal(idx) {
  const m = (S.mealPlan || [])[idx];
  if (!m) return;

  // Parse ingredients from comma-separated string or array
  let ingList = [];
  if (Array.isArray(m.ingredients)) {
    ingList = m.ingredients;
  } else if (typeof m.ingredients === 'string' && m.ingredients) {
    ingList = m.ingredients.split(',').map(s => s.trim()).filter(Boolean);
  }

  // Detect YouTube URL in source_url / youtube_url / url fields
  const srcUrl = m.source_url || m.youtube_url || m.url || '';
  const ytMatch = srcUrl.match(/(?:youtu\.be\/|v=|embed\/|shorts\/)([A-Za-z0-9_-]{11})/);
  const ytId = ytMatch ? ytMatch[1] : null;

  // Stars from rating (base + adjustment)
  const baseRating = parseFloat(m.AggregatedRating || m.rating || 0);
  const adj = _ratingAdjustments[m.name] || 0;
  const effectiveRating = Math.max(0, Math.min(5, baseRating + adj * 0.5));
  const rating = effectiveRating;
  const stars = rating > 0
    ? '★'.repeat(Math.round(rating)).padEnd(5, '☆').slice(0, 5)
    : '';
  const adjLabel = adj !== 0
    ? ` <span style="font-size:.75rem;color:${adj > 0 ? '#10b981' : '#f43f5e'};font-weight:600">(${adj > 0 ? '+' : ''}${adj.toFixed(2)} adj)</span>`
    : '';

  const overlay = document.createElement('div');
  overlay.className = 'meal-modal-overlay';
  overlay.id = 'meal-modal-overlay';
  overlay.onclick = (e) => { if (e.target === overlay) closeMealModal(); };
  overlay.innerHTML = `
    <div class="meal-modal" onclick="event.stopPropagation()">
      <div class="meal-modal-header">
        <div>
          <div class="meal-modal-slot">${m.Meal || ''} · ${m.Day || ''}</div>
          <h2>${m.name || 'Recipe'}</h2>
        </div>
        <button class="meal-modal-close" onclick="closeMealModal()" title="Close">✕</button>
      </div>
      <div class="meal-modal-body">

        <!-- Macros -->
        <div>
          <div class="meal-modal-macros">
            <div class="meal-modal-macro"><span class="macro-lbl">🔥 Calories</span><span class="macro-num">${Math.round(m.calories||0)}<small style="font-size:.65rem;font-weight:500"> kcal</small></span></div>
            <div class="meal-modal-macro"><span class="macro-lbl">💪 Protein</span><span class="macro-num">${Math.round(m.protein||0)}<small style="font-size:.65rem;font-weight:500">g</small></span></div>
            <div class="meal-modal-macro"><span class="macro-lbl">🌾 Carbs</span><span class="macro-num">${Math.round(m.carbs||0)}<small style="font-size:.65rem;font-weight:500">g</small></span></div>
            <div class="meal-modal-macro"><span class="macro-lbl">🫒 Fat</span><span class="macro-num">${Math.round(m.fat||0)}<small style="font-size:.65rem;font-weight:500">g</small></span></div>
          </div>
        </div>

        <!-- Meta -->
        <div class="meal-modal-meta">
          ${m.prep_time ? `<span><i class="fa-solid fa-clock"></i> ${m.prep_time} min</span>` : ''}
          ${rating > 0 ? `<span><i class="fa-solid fa-star" style="color:#f59e0b"></i> ${rating.toFixed(1)} ${stars}${adjLabel}</span>` : ''}
          ${m.cost ? `<span><i class="fa-solid fa-euro-sign"></i> €${parseFloat(m.cost).toFixed(2)}</span>` : ''}
          ${m.RecipeCategory || m.category ? `<span><i class="fa-solid fa-tag"></i> ${m.RecipeCategory || m.category}</span>` : ''}
        </div>

        <!-- Ingredients -->
        ${ingList.length ? `
        <div>
          <div class="meal-modal-section-title"><i class="fa-solid fa-list-ul"></i> Ingredients</div>
          <div class="meal-modal-ingredients">
            ${ingList.map(ing => `<span class="meal-modal-ingredient-tag">${ing}</span>`).join('')}
          </div>
        </div>` : ''}

        <!-- Instructions -->
        ${m.instructions ? `
        <div>
          <div class="meal-modal-section-title"><i class="fa-solid fa-book-open"></i> Instructions</div>
          <div class="meal-modal-instructions">${m.instructions.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>
        </div>` : ''}

        <!-- YouTube embed -->
        ${ytId ? `
        <div>
          <div class="meal-modal-section-title"><i class="fa-brands fa-youtube" style="color:#ef4444"></i> Video Recipe</div>
          <div class="meal-modal-youtube">
            <iframe src="https://www.youtube.com/embed/${ytId}" allowfullscreen loading="lazy"></iframe>
          </div>
        </div>` : (srcUrl && !ytId ? `
        <div>
          <a class="meal-modal-link" href="${srcUrl}" target="_blank" rel="noopener">
            <i class="fa-solid fa-arrow-up-right-from-square"></i> View original recipe
          </a>
        </div>` : '')}

      </div>
    </div>`;

  document.body.appendChild(overlay);
  document.addEventListener('keydown', _mealModalKeyHandler);
}

function closeMealModal() {
  const el = document.getElementById('meal-modal-overlay');
  if (el) el.remove();
  document.removeEventListener('keydown', _mealModalKeyHandler);
}
function _mealModalKeyHandler(e) { if (e.key === 'Escape') closeMealModal(); }

// ── Meal swap panel ────────────────────────────────────────────────────────────
let _activeSwapIdx = null;
let _swapSearchTimer = null;
const _swapRecipeStore = {};   // key: "idx-storeKey" → recipe object
let _swapStoreCounter = 0;

function toggleSwapPanel(idx) {
  if (_activeSwapIdx === idx) { closeSwapPanel(idx); return; }
  if (_activeSwapIdx !== null) closeSwapPanel(_activeSwapIdx);
  _activeSwapIdx = idx;
  const panel = document.getElementById(`swap-panel-${idx}`);
  if (!panel) return;
  panel.style.display = 'block';
  // Mark the swap button active
  const card = document.getElementById(`meal-card-${idx}`);
  card?.querySelector('.swap-btn')?.classList.add('active');
  // Load suggestions
  _loadSwapSuggestions(idx);
  // Focus search
  setTimeout(() => document.getElementById(`swap-search-${idx}`)?.focus(), 100);
}

function closeSwapPanel(idx) {
  const panel = document.getElementById(`swap-panel-${idx}`);
  if (panel) panel.style.display = 'none';
  const card = document.getElementById(`meal-card-${idx}`);
  card?.querySelector('.swap-btn')?.classList.remove('active');
  if (_activeSwapIdx === idx) _activeSwapIdx = null;
}

async function _loadSwapSuggestions(idx) {
  const m = (S.mealPlan || [])[idx];
  if (!m) return;
  const suggBox = document.getElementById(`swap-sugg-${idx}`);
  if (!suggBox) return;
  suggBox.innerHTML = '<div class="swap-loading"><i class="fa-solid fa-spinner fa-spin"></i> Loading…</div>';
  try {
    const res = await fetch('/api/meal-plan/suggestions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot: m.Meal || 'Lunch', calories: m.calories || 400, exclude: m.name || '' })
    });
    const data = await res.json();
    if (!data.ok || !data.suggestions?.length) {
      suggBox.innerHTML = '<div class="swap-empty">No similar recipes found.</div>';
      return;
    }
    suggBox.innerHTML = data.suggestions.map(r => _swapCardHTML(idx, r)).join('');
  } catch {
    suggBox.innerHTML = '<div class="swap-empty">Could not load suggestions.</div>';
  }
}

let _swapSearchCache = {};
async function onSwapSearch(idx, query) {
  clearTimeout(_swapSearchTimer);
  const box = document.getElementById(`swap-search-results-${idx}`);
  if (!box) return;
  if (!query.trim()) { box.innerHTML = ''; return; }
  box.innerHTML = '<div class="swap-loading"><i class="fa-solid fa-spinner fa-spin"></i></div>';
  _swapSearchTimer = setTimeout(async () => {
    const q = query.trim();
    if (_swapSearchCache[q]) { box.innerHTML = _swapSearchCache[q]; return; }
    try {
      const res = await fetch(`/api/recipes/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      if (!data.ok || !data.results?.length) {
        box.innerHTML = '<div class="swap-empty">No matches found.</div>';
        return;
      }
      const html = data.results.map(r => _swapCardHTML(idx, r)).join('');
      _swapSearchCache[q] = html;
      box.innerHTML = html;
    } catch {
      box.innerHTML = '<div class="swap-empty">Search failed.</div>';
    }
  }, 300);
}

function _swapCardHTML(idx, r) {
  const cal  = Math.round(parseFloat(r.calories) || 0);
  const prot = Math.round(parseFloat(r.protein)  || 0);
  const cost = parseFloat(r.cost);
  const costStr = cost > 0 ? `· €${cost.toFixed(2)}` : '';
  const cat  = r.RecipeCategory || r.category || '';
  const key = `${idx}-${_swapStoreCounter++}`;
  _swapRecipeStore[key] = r;
  return `<div class="swap-suggestion-card" onclick="swapMeal(${idx}, '${key}')">
    <div class="swap-sugg-name">${r.name || 'Recipe'}</div>
    <div class="swap-sugg-meta">${cal} kcal · ${prot}g protein ${costStr}${cat ? ' · ' + cat : ''}</div>
  </div>`;
}

function swapMeal(idx, storeKey) {
  const recipe = _swapRecipeStore[storeKey];
  if (!recipe) return;
  const current = (S.mealPlan || [])[idx];
  if (!current) return;
  // Preserve Day and Meal slot from current entry
  const swapped = { ...recipe, Day: current.Day, Meal: current.Meal };
  S.mealPlan[idx] = swapped;
  closeSwapPanel(idx);
  // Re-render just the card in place
  const card = document.getElementById(`meal-card-${idx}`);
  if (card) {
    const m = swapped;
    const adj = _ratingAdjustments[m.name] || 0;
    card.querySelector('.meal-slot').textContent = m.Meal || '';
    card.querySelector('.meal-name').textContent = m.name || 'Unknown';
    // Update macro values
    const vals = card.querySelectorAll('.macro-val');
    const macros = [Math.round(m.calories||0)+' kcal', Math.round(m.protein||0)+'g', Math.round(m.carbs||0)+'g', Math.round(m.fat||0)+'g'];
    vals.forEach((v, i) => { if (macros[i]) v.textContent = macros[i]; });
    // Update card onclick for modal
    card.setAttribute('onclick', `openMealModal(${idx})`);
    // Rebuild rating badge
    _updateRatingBadge(idx, m.name);
    // Clear swap search cache since user navigated
    _swapSearchCache = {};
  }
  toast(`Swapped to ${recipe.name}`, 'success');
}

// In-memory cache of rating adjustments for the current session
let _ratingAdjustments = {};

async function loadRatingAdjustments() {
  try {
    const res = await fetch('/api/ratings').then(r => r.json());
    _ratingAdjustments = res.adjustments || {};
    // Refresh all visible badges
    document.querySelectorAll('[id^="rating-badge-"]').forEach(badge => {
      const idx = parseInt(badge.id.replace('rating-badge-', ''));
      const meal = (S.mealPlan || [])[idx];
      if (meal) _updateRatingBadge(idx, meal.name);
    });
  } catch (e) { /* ignore */ }
}

function _updateRatingBadge(cardIdx, recipeName) {
  const badge = document.getElementById(`rating-badge-${cardIdx}`);
  if (!badge) return;
  const adj = _ratingAdjustments[recipeName] || 0;
  if (adj === 0) { badge.textContent = ''; return; }
  const sign = adj > 0 ? '+' : '';
  badge.textContent = `${sign}${adj.toFixed(2)}`;
  badge.style.color = adj > 0 ? 'var(--primary)' : '#ef4444';
}

async function rateRecipe(name, delta, cardIdx) {
  try {
    const res = await api.post('/api/rating', { recipe_name: name, delta });
    if (res.ok) {
      _ratingAdjustments[name] = res.new_value;
      if (cardIdx !== undefined) _updateRatingBadge(cardIdx, name);
      // Small inline toast showing the new total
      const sign = res.new_value >= 0 ? '+' : '';
      toast(`${name.length > 20 ? name.slice(0,20)+'…' : name}: ${sign}${res.new_value.toFixed(2)}`, 'success');
    }
  } catch (e) { /* ignore */ }
}

async function generateShoppingList() {
  if (!S.mealPlan) return;
  S.plannerStep = 3;
  renderPlanner(document.getElementById('content'));
  document.getElementById('planner-content').innerHTML = `<div class="loading-overlay"><div class="spinner"></div><div>Generating smart shopping list...<br><span class="text-sm text-muted">Matching ingredients to Mercadona products via AI</span></div></div>`;

  // Extract ingredients from meal plan
  const items = [];
  S.mealPlan.forEach(m => {
    if (m.ingredients_json) {
      try {
        const parsed = JSON.parse(m.ingredients_json);
        parsed.forEach(p => items.push({ Ingredient: p.i, Quantity: p.q }));
      } catch (e) { /* skip */ }
    } else if (m.ingredients) {
      m.ingredients.split(',').forEach(ing => items.push({ Ingredient: ing.trim(), Quantity: '' }));
    }
  });

  try {
    const res = await api.post('/api/shopping-list/generate', { items, groq_key: S.settings.groqKey, people: S._planParams?.people || 1 });
    if (res.ok && res.shopping_list) {
      S.shoppingList = res.shopping_list;
      save('shoppingList');
      toast('Shopping list ready!', 'success');
    } else {
      toast(res.error || 'Failed to generate shopping list', 'error');
    }
  } catch (e) {
    toast('Network error: ' + e.message, 'error');
  }
  renderPlannerShop(document.getElementById('planner-content'));
}

function renderPlannerShop(el) {
  if (!S.shoppingList || !S.shoppingList.length) {
    el.innerHTML = `<div class="empty-state"><i class="fa-solid fa-cart-shopping"></i><p>No shopping list yet. Generate one from your meal plan.</p>
      <button class="btn-secondary mt-2" onclick="S.plannerStep=2;renderPlanner(document.getElementById('content'))"><i class="fa-solid fa-arrow-left"></i> Back to Review</button></div>`;
    return;
  }

  const total = S.shoppingList.reduce((s, i) => s + (parseFloat(i['Total Price']) || 0), 0);
  el.innerHTML = `
    <div class="flex-between mb-2">
      <div class="btn-group">
        <button class="btn-secondary" onclick="S.plannerStep=2;renderPlanner(document.getElementById('content'))"><i class="fa-solid fa-arrow-left"></i> Back</button>
        <button class="btn-primary" onclick="addAllToBasket()"><i class="fa-solid fa-basket-shopping"></i> Add All to Basket</button>
        <button class="btn-secondary" id="btn-debate" onclick="runDebate()" title="Budget Optimizer vs Nutritionist — two AI agents argue about your basket"><i class="fa-solid fa-scale-balanced"></i> Debate this basket</button>
      </div>
    </div>
    <div class="shopping-legend text-sm text-muted mb-1">
      <span class="legend-swatch legend-exact"></span> Exact match
      <span class="legend-swatch legend-alternative"></span> Alternative (hover <i class="fa-solid fa-circle-info"></i> for why)
      <span class="legend-swatch legend-missing"></span> No match found
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Ingredient</th><th>Qty Needed</th><th>Mercadona Product</th><th>Pack Size</th><th>Count</th><th>Unit Price</th><th>Total</th><th style="white-space:nowrap">Actions</th></tr></thead>
        <tbody>
          ${S.shoppingList.map((item, i) => {
            const mq = (item.match_quality || 'exact');
            const reason = (item.match_reason || '').replace(/"/g, '&quot;');
            const rowCls = mq === 'alternative' ? 'row-alternative' : (mq === 'none' ? 'row-missing' : '');
            const badge = mq === 'alternative'
              ? ` <i class="fa-solid fa-circle-info match-badge" title="${reason || 'Alternative match'}"></i>`
              : (mq === 'none' ? ` <i class="fa-solid fa-triangle-exclamation match-badge" title="${reason || 'No match found'}"></i>` : '');
            const skuText = item.SKU || '';
            const skuCell = item.Link
              ? `<a href="${item.Link}" target="_blank">${skuText}</a>${badge}`
              : `${skuText}${badge}`;
            const titleAttr = reason ? ` title="${reason}"` : '';
            return `<tr class="${rowCls}"${titleAttr}>
              <td><strong>${item.Ingredient || ''}</strong></td>
              <td>${item['Qty Needed'] || ''}</td>
              <td>${skuCell}</td>
              <td>${item['Pack Size'] || ''}</td>
              <td>${item.Count || 1}</td>
              <td>&euro;${(parseFloat(item['Unit Price']) || 0).toFixed(2)}</td>
              <td><strong>&euro;${(parseFloat(item['Total Price']) || 0).toFixed(2)}</strong></td>
              <td style="white-space:nowrap">
                <button class="btn-shop-action btn-shop-add" title="Add to basket" onclick='addShopItemToBasket(${i})'><i class="fa-solid fa-basket-shopping"></i> Add</button>
                <button class="btn-shop-action btn-shop-remove" title="Remove from list" onclick='removeShopItem(${i})'><i class="fa-solid fa-xmark"></i> Remove</button>
                <button class="btn-shop-action btn-shop-alt" title="Find alternative products" onclick='findAlternative(${i})'><i class="fa-solid fa-arrows-rotate"></i> Alternative</button>
              </td>
            </tr>
            <tr id="alt-panel-${i}" class="alt-panel-row" style="display:none">
              <td colspan="8">
                <div class="alt-panel" id="alt-panel-content-${i}"></div>
              </td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>
    <div class="basket-summary mt-2">
      <span>Estimated Total</span>
      <span class="basket-total">&euro;${total.toFixed(2)}</span>
    </div>
    <div id="debate-section" style="margin-top:20px;display:none">
      <h3 class="debate-title">
        <i class="fa-solid fa-scale-balanced" style="color:var(--primary);margin-right:6px"></i>AI Agent Debate
        <span class="tag" style="margin-left:8px;font-size:.7rem">Memory · Tools · Planning · Feedback</span>
      </h3>
      <div class="debate-agent-pills" id="debate-pills">
        <button class="debate-pill active" data-agent="budget"    onclick="toggleDebateAgent('budget')">💰 Budget</button>
        <button class="debate-pill active" data-agent="nutrition" onclick="toggleDebateAgent('nutrition')">🥗 Nutritionist</button>
        <button class="debate-pill active" data-agent="moderator" onclick="toggleDebateAgent('moderator')">⚖️ Moderator</button>
        <button class="btn-debate-all" onclick="debateAll()"><i class="fa-solid fa-comments"></i> Debate All</button>
        <button class="btn-debate-clear" onclick="clearDebate()"><i class="fa-solid fa-trash-can"></i> Clear</button>
      </div>
      <div class="debate-thread" id="debate-thread">
        <div class="debate-thread-empty" id="debate-empty-hint">Click <strong>Debate All</strong> to start, or select agents and type a message below.</div>
      </div>
      <div class="debate-input-wrap">
        <input type="text" id="debate-input"
          placeholder="Ask agents… or type @budget @nutritionist @moderator to target"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendDebateMessage();}"
          oninput="detectDebateMention(this.value)" />
        <button id="debate-send-btn" onclick="sendDebateMessage()"><i class="fa-solid fa-paper-plane"></i></button>
      </div>
    </div>
    <div style="margin-top:20px">
      <h3 style="font-size:.9rem;font-weight:600;margin-bottom:8px"><i class="fa-solid fa-chart-pie"></i> Shopping Analytics</h3>
      <iframe id="dash-shopping" src="/dash/shopping?t=${Date.now()}" style="width:100%;height:600px;border:none;border-radius:6px" loading="lazy"></iframe>
    </div>
  `;
}

function addShopItemToBasket(idx) {
  const item = S.shoppingList[idx];
  if (!item) return;
  addToBasket({ name: item.SKU || item.Ingredient, price: parseFloat(item['Unit Price']) || 0, qty: item['Pack Size'] || '1 unit', url: item.Link || '', count: parseInt(item.Count) || 1 });
}

function addAllToBasket() {
  S.shoppingList.forEach((item) => {
    S.basket.push({ name: item.SKU || item.Ingredient, price: parseFloat(item['Unit Price']) || 0, qty: item['Pack Size'] || '1 unit', url: item.Link || '', count: parseInt(item.Count) || 1 });
  });
  save('basket'); updateBadge();
  toast(`Added ${S.shoppingList.length} items to basket`, 'success');
}

async function packFeedback(idx, vote) {
  const item = S.shoppingList[idx];
  if (!item) return;
  try {
    await api.post('/api/feedback/pack', {
      ingredient: item.Ingredient || '',
      sku: item.SKU || '',
      vote,
    });
    toast(vote === 'up' ? 'Thanks! Pack size noted as correct.' : 'Got it — will suggest more packs next time.', 'success');
  } catch (e) {
    toast('Could not save feedback', 'error');
  }
}

function removeShopItem(idx) {
  S.shoppingList.splice(idx, 1);
  save('shoppingList');
  renderPlannerShop(document.getElementById('content'));
  toast('Item removed from list', 'success');
}

// Cache for alternatives per item index (cleared on re-render)
const _altCache = {};

async function findAlternative(idx) {
  const item = S.shoppingList[idx];
  if (!item) return;

  const panelRow = document.getElementById(`alt-panel-${idx}`);
  const panelContent = document.getElementById(`alt-panel-content-${idx}`);
  if (!panelRow || !panelContent) return;

  // Toggle: if already open, close it
  if (panelRow.style.display !== 'none') {
    panelRow.style.display = 'none';
    return;
  }

  panelRow.style.display = 'table-row';
  panelContent.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Searching Mercadona for alternatives…';

  try {
    const q = item.Ingredient || item.SKU || '';
    const res = await api.get(`/api/mercadona/search?q=${encodeURIComponent(q)}&top_k=5`);
    const products = (res.products || []).slice(0, 5);
    _altCache[idx] = products;

    if (products.length) {
      panelContent.innerHTML = `
        <div class="alt-panel-header">5 closest Mercadona alternatives for <strong>${q}</strong></div>
        ${products.map((p, j) => `
          <div class="alt-option">
            <div class="alt-option-info">
              ${p.url || p.URL ? `<a href="${p.url || p.URL}" target="_blank" class="alt-option-name">${p.name || p.Name || ''}</a>` : `<span class="alt-option-name">${p.name || p.Name || ''}</span>`}
              <span class="alt-option-meta">${p.unit || p.Unit || ''} &nbsp;·&nbsp; <strong>&euro;${parseFloat(p.price || p.Price || 0).toFixed(2)}</strong></span>
            </div>
            <button class="btn-shop-action btn-shop-add" style="padding:4px 10px;font-size:.72rem" onclick='pickAlternative(${idx},${j})'>Use this</button>
          </div>
        `).join('')}
      `;
    } else {
      panelContent.innerHTML = '<span class="text-muted text-sm">No alternatives found in Mercadona catalogue.</span>';
    }
  } catch (e) {
    panelContent.innerHTML = `<span style="color:var(--error)" class="text-sm">Error loading alternatives: ${e.message}</span>`;
  }
}

function pickAlternative(itemIdx, altIdx) {
  const products = _altCache[itemIdx];
  if (!products || !products[altIdx]) return;
  const p = products[altIdx];
  const item = S.shoppingList[itemIdx];
  if (!item) return;

  // Replace item fields with the chosen alternative
  item.SKU = p.name || p.Name || item.SKU;
  item.Link = p.url || p.URL || '';
  item['Unit Price'] = parseFloat(p.price || p.Price || 0);
  item['Pack Size'] = p.unit || p.Unit || item['Pack Size'];
  item['Total Price'] = item['Unit Price'] * (parseInt(item.Count) || 1);
  item.match_quality = 'alternative';
  item.match_reason = 'Manually selected alternative';

  save('shoppingList');
  renderPlannerShop(document.getElementById('content'));
  toast(`Switched to: ${item.SKU}`, 'success');
}

// ── Debate chat helpers ───────────────────────────────────────────────────────

function toggleDebateAgent(agentId) {
  if (_debateActiveAgents.has(agentId)) {
    _debateActiveAgents.delete(agentId);
  } else {
    _debateActiveAgents.add(agentId);
  }
  document.querySelectorAll('.debate-pill').forEach(btn => {
    btn.classList.toggle('active', _debateActiveAgents.has(btn.dataset.agent));
  });
}

function clearDebate() {
  _debateHistory = [];
  const thread = document.getElementById('debate-thread');
  if (thread) thread.innerHTML = '<div class="debate-thread-empty" id="debate-empty-hint">Click <strong>Debate All</strong> to start, or select agents and type a message below.</div>';
}

function _appendDebateBubble(role, agentId, content) {
  const thread = document.getElementById('debate-thread');
  if (!thread) return;
  // Remove empty-state hint on first message
  const hint = document.getElementById('debate-empty-hint');
  if (hint) hint.remove();

  const div = document.createElement('div');

  if (role === 'user') {
    // Escape HTML in content, then convert newlines to <br>
    const safe = content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    div.className = 'debate-bubble user-bubble';
    div.innerHTML = `
      <div class="debate-avatar">🧑</div>
      <div class="debate-bubble-content">${safe}</div>`;
  } else {
    // Parse out action block before rendering
    const { displayText, actions } = _parseDebateActions(content);
    const safe = displayText.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
    const cfg = DEBATE_AGENTS[agentId] || { emoji: '🤖', label: agentId, cls: '' };
    div.className = `debate-bubble ${cfg.cls}`;
    div.innerHTML = `
      <div class="debate-avatar">${cfg.emoji}</div>
      <div style="min-width:0;flex:1">
        <div class="debate-agent-label">${cfg.label}</div>
        <div class="debate-bubble-content" id="debate-bc-${Date.now()}">${safe}</div>
      </div>`;
    // Inject action buttons into the bubble-content div after creation
    if (actions.length) {
      // We need a reference after innerHTML is set — use the last element
      setTimeout(() => {
        const bubbleContent = div.querySelector('.debate-bubble-content');
        if (bubbleContent) _renderDebateActions(actions, bubbleContent);
      }, 0);
    }
  }
  thread.appendChild(div);
  thread.scrollTop = thread.scrollHeight;
}

function _addDebateTyping(agentId) {
  const thread = document.getElementById('debate-thread');
  if (!thread) return null;
  const hint = document.getElementById('debate-empty-hint');
  if (hint) hint.remove();
  const cfg = DEBATE_AGENTS[agentId] || { emoji: '🤖', label: agentId, cls: '' };
  const div = document.createElement('div');
  div.className = `debate-bubble ${cfg.cls}`;
  div.id = `debate-typing-${agentId}`;
  div.innerHTML = `
    <div class="debate-avatar">${cfg.emoji}</div>
    <div>
      <div class="debate-agent-label">${cfg.label}</div>
      <div class="debate-bubble-content debate-typing-dots">⚙️ Running tools…</div>
    </div>`;
  thread.appendChild(div);
  thread.scrollTop = thread.scrollHeight;
  return div;
}

function detectDebateMention(value) {
  const lower = value.toLowerCase();
  const hasBudget     = lower.includes('@budget');
  const hasNutrition  = lower.includes('@nutritionist');
  const hasModerator  = lower.includes('@moderator');
  if (hasBudget || hasNutrition || hasModerator) {
    _debateActiveAgents = new Set();
    if (hasBudget)    _debateActiveAgents.add('budget');
    if (hasNutrition) _debateActiveAgents.add('nutrition');
    if (hasModerator) _debateActiveAgents.add('moderator');
    document.querySelectorAll('.debate-pill').forEach(btn => {
      btn.classList.toggle('active', _debateActiveAgents.has(btn.dataset.agent));
    });
  }
}

async function debateAll() {
  // Activate all three agents
  _debateActiveAgents = new Set(['budget', 'nutrition', 'moderator']);
  document.querySelectorAll('.debate-pill').forEach(btn => btn.classList.add('active'));
  // Populate a default prompt and fire
  const input = document.getElementById('debate-input');
  if (input) input.value = 'Analyse this basket and share your perspective.';
  await sendDebateMessage();
}

// ── Debate action parsing & execution ─────────────────────────────────────────

function _parseDebateActions(rawContent) {
  // Splits "text\n---ACTIONS---\n[{...}]" → { displayText, actions }
  const sep = '---ACTIONS---';
  const sepIdx = rawContent.indexOf(sep);
  if (sepIdx === -1) return { displayText: rawContent.trim(), actions: [] };

  const displayText = rawContent.slice(0, sepIdx).trim();
  const jsonPart    = rawContent.slice(sepIdx + sep.length).trim();
  let actions = [];
  try {
    const parsed = JSON.parse(jsonPart);
    if (Array.isArray(parsed)) actions = parsed;
  } catch (_) { /* malformed JSON — ignore actions */ }
  return { displayText, actions };
}

function _renderDebateActions(actions, bubbleContentEl) {
  if (!actions || !actions.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'debate-actions';
  actions.forEach((act, i) => {
    const btn = document.createElement('button');
    const isReplace = act.type === 'replace';
    btn.className = `debate-action-btn ${isReplace ? 'btn-replace' : 'btn-add'}`;
    btn.innerHTML = `<i class="fa-solid fa-${isReplace ? 'arrows-rotate' : 'basket-shopping'}"></i> ${act.label || (isReplace ? 'Replace' : 'Add to basket')}`;
    btn.onclick = () => _executeDebateAction(act, btn);
    wrap.appendChild(btn);
  });
  bubbleContentEl.appendChild(wrap);
}

async function _executeDebateAction(act, btn) {
  const query = act.query || act.label || '';
  if (!query) { toast('No search query for this action', 'error'); return; }

  btn.classList.add('btn-loading');
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Searching…';

  try {
    const res = await api.get(`/api/mercadona/search?q=${encodeURIComponent(query)}&top_k=3`);
    if (!res.ok || !res.products || !res.products.length) {
      toast(`No Mercadona product found for "${query}"`, 'error');
      btn.classList.remove('btn-loading');
      btn.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Not found`;
      return;
    }

    const product = res.products[0]; // best TF-IDF match
    const name    = product.name || query;
    const price   = parseFloat(product.price) || 0;
    const unit    = product.unit || '';
    const url     = product.url || product.link || '';

    if (act.type === 'replace' && act.remove) {
      // Remove old item from basket (if present), add new one
      const oldIdx = S.basket.findIndex(b => b.name.toLowerCase().includes((act.remove || '').toLowerCase()));
      if (oldIdx !== -1) S.basket.splice(oldIdx, 1);
    }

    addToBasket({ name, price, qty: unit, url, count: 1 });
    toast(`✅ Added "${name}" to basket (€${price.toFixed(2)})`, 'success');

    // Update button to show success + product name
    btn.classList.remove('btn-loading');
    btn.innerHTML = `<i class="fa-solid fa-check"></i> Added — ${name.slice(0, 28)}${name.length > 28 ? '…' : ''}`;
    btn.disabled = true;
    btn.style.background = '#10b981';
  } catch (e) {
    toast('Search error: ' + e.message, 'error');
    btn.classList.remove('btn-loading');
    btn.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Error`;
  }
}

async function sendDebateMessage() {
  if (!S.shoppingList || !S.shoppingList.length) {
    toast('Generate a shopping list first', 'error'); return;
  }
  const input = document.getElementById('debate-input');
  const message = (input ? input.value.trim() : '') || 'Analyse this basket and share your perspective.';

  const agents = Array.from(_debateActiveAgents);
  if (!agents.length) { toast('Select at least one agent first', 'error'); return; }

  // Show section
  const section = document.getElementById('debate-section');
  if (section) section.style.display = 'block';
  if (input) input.value = '';

  // Append user bubble + push to history
  _appendDebateBubble('user', null, message);
  // Save history snapshot before pushing user msg so each agent gets the pre-turn history
  const historySnapshot = [..._debateHistory];
  _debateHistory.push({ role: 'user', agent: null, content: message });

  // Disable controls while running
  const sendBtn = document.getElementById('debate-send-btn');
  if (sendBtn) sendBtn.disabled = true;
  if (input) input.disabled = true;

  // Run each selected agent sequentially
  for (const agentId of agents) {
    const typingEl = _addDebateTyping(agentId);
    try {
      const res = await api.post('/api/debate/chat', {
        agents:  [agentId],
        message,
        history: historySnapshot,
        items:   S.shoppingList,
        api_key: S.settings.groqKey,
      });
      if (typingEl) typingEl.remove();
      if (res.ok && res.replies && res.replies.length) {
        const reply = res.replies[0];
        _appendDebateBubble('agent', reply.agent, reply.content);
        _debateHistory.push({ role: 'agent', agent: reply.agent, content: reply.content });
      } else {
        const errMsg = `(Error: ${res.error || 'unknown'})`;
        _appendDebateBubble('agent', agentId, errMsg);
        _debateHistory.push({ role: 'agent', agent: agentId, content: errMsg });
      }
    } catch (e) {
      if (typingEl) typingEl.remove();
      const errMsg = `(Network error: ${e.message})`;
      _appendDebateBubble('agent', agentId, errMsg);
    }
  }

  // Re-enable controls
  if (sendBtn) sendBtn.disabled = false;
  if (input) { input.disabled = false; input.focus(); }
}

// ── Legacy entry-point (called from "Debate this basket" button) ──────────────
async function runDebate() {
  if (!S.shoppingList || !S.shoppingList.length) {
    toast('Generate a shopping list first', 'error'); return;
  }
  // Show the debate chat section and scroll to it, then auto-start
  const section = document.getElementById('debate-section');
  if (section) { section.style.display = 'block'; section.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  // Reset history for a fresh debate
  clearDebate();
  // Re-activate all agents and kick off the initial analysis
  await debateAll();
}

// ── Basket drag & drop ────────────────────────────────────────────────────────
function _initBasketDragDrop() {
  const list = document.getElementById('basket-list');
  if (!list) return;
  let dragged = null;
  list.querySelectorAll('.basket-item').forEach(item => {
    item.addEventListener('dragstart', () => { dragged = item; setTimeout(() => item.classList.add('dragging'), 0); });
    item.addEventListener('dragend', () => { item.classList.remove('dragging'); list.querySelectorAll('.basket-item').forEach(i => i.classList.remove('drag-over')); });
    item.addEventListener('dragover', e => { e.preventDefault(); if (item !== dragged) { list.querySelectorAll('.basket-item').forEach(i => i.classList.remove('drag-over')); item.classList.add('drag-over'); } });
    item.addEventListener('drop', e => {
      e.preventDefault(); item.classList.remove('drag-over');
      if (dragged && dragged !== item) {
        const kids = [...list.children];
        const from = kids.indexOf(dragged), to = kids.indexOf(item);
        if (from > -1 && to > -1) { const [m] = S.basket.splice(from, 1); S.basket.splice(to, 0, m); renderBasket(document.getElementById('content')); }
      }
    });
  });
}

// ── Basket ───────────────────────────────────────────────────────────────────
function renderBasket(el) {
  const total = S.basket.reduce((s, i) => s + (i.price * (i.count || 1)), 0);

  el.innerHTML = `
    <div class="search-bar" id="merc-search-wrap">
      <i class="fa-solid fa-magnifying-glass"></i>
      <input type="search" id="merc-search" placeholder="Search Mercadona products..." autocomplete="off">
      <div class="search-results" id="merc-results"></div>
    </div>

    ${S.basket.length ? `
    <div class="basket-grid">
      <div class="basket-items">
        <div id="basket-list">
          ${S.basket.map((item, i) => `
          <div class="basket-item" draggable="true" data-idx="${i}">
            <span class="drag-handle"><i class="fa-solid fa-grip-vertical"></i></span>
            <div class="item-dot">${item.name ? item.name[0].toUpperCase() : '?'}</div>
            <div class="item-info">
              <div class="item-name">${item.url ? `<a href="${item.url}" target="_blank" style="color:inherit">${item.name}</a>` : item.name}</div>
              <div class="item-sub">${item.qty || ''}</div>
            </div>
            <div class="item-qty">
              <button class="qty-btn" onclick="changeBasketCount(${i}, -1)"><i class="fa-solid fa-minus"></i></button>
              <span class="qty-num">${item.count || 1}</span>
              <button class="qty-btn" onclick="changeBasketCount(${i}, 1)"><i class="fa-solid fa-plus"></i></button>
            </div>
            <span class="item-price">&euro;${((item.price || 0) * (item.count || 1)).toFixed(2)}</span>
            <button class="item-remove" title="Remove" onclick="removeBasketItem(${i})"><i class="fa-solid fa-trash"></i></button>
          </div>`).join('')}
        </div>
      </div>
      <div class="basket-summary-card">
        <h3>Order Summary</h3>
        <div class="summary-row"><span class="text-muted">${S.basket.length} item(s)</span><span>&euro;${total.toFixed(2)}</span></div>
        <div class="summary-total"><span>Total</span><span>&euro;${total.toFixed(2)}</span></div>
        <div class="btn-group mt-2" style="flex-direction:column">
          <button class="btn-primary" style="width:100%;justify-content:center" onclick="confirmPurchase()"><i class="fa-solid fa-check"></i> Confirm Purchase</button>
          <button class="btn-ghost" style="width:100%;justify-content:center" onclick="clearBasket()"><i class="fa-solid fa-trash"></i> Clear Basket</button>
        </div>
      </div>
    </div>
    ` : `
    <div class="basket-empty">
      <i class="fa-solid fa-basket-shopping"></i>
      <p>Your basket is empty</p>
      <p class="text-sm text-muted mt-1">Search for products above or generate a shopping list from the Meal Planner</p>
    </div>`}
  `;

  // Init drag and drop
  if (S.basket.length) _initBasketDragDrop();

  // Mercadona search
  let searchTimeout;
  const searchInput = document.getElementById('merc-search');
  const resultsEl = document.getElementById('merc-results');
  searchInput?.addEventListener('input', () => {
    clearTimeout(searchTimeout);
    const q = searchInput.value.trim();
    if (q.length < 2) { resultsEl.classList.remove('show'); return; }
    searchTimeout = setTimeout(async () => {
      try {
        const res = await api.get(`/api/mercadona/search?q=${encodeURIComponent(q)}&top_k=8`);
        if (res.ok && res.products.length) {
          resultsEl.innerHTML = res.products.map(p => `
            <div class="search-result-item" data-product='${JSON.stringify(p).replace(/'/g,"&#39;")}'>
              <span>${p.name}</span>
              <span class="search-result-price">&euro;${(parseFloat(p.price) || 0).toFixed(2)}</span>
            </div>`).join('');
          resultsEl.classList.add('show');
          resultsEl.querySelectorAll('.search-result-item').forEach(item => {
            item.addEventListener('click', () => {
              const p = JSON.parse(item.dataset.product);
              addToBasket({ name: p.name, price: p.price, qty: p.unit || '1 unit', url: p.url || '' });
              resultsEl.classList.remove('show');
              searchInput.value = '';
              renderBasket(el);
            });
          });
        } else { resultsEl.innerHTML = '<div class="search-result-item">No results found</div>'; resultsEl.classList.add('show'); }
      } catch (e) { /* ignore */ }
    }, 350);
  });

  // Close search results on outside click
  document.addEventListener('click', (e) => {
    if (!document.getElementById('merc-search-wrap')?.contains(e.target)) resultsEl?.classList.remove('show');
  }, { once: false });
}

function changeBasketCount(idx, delta) {
  if (!S.basket[idx]) return;
  S.basket[idx].count = Math.max(1, (S.basket[idx].count || 1) + delta);
  save('basket');
  renderBasket(document.getElementById('content'));
}

function removeBasketItem(idx) {
  S.basket.splice(idx, 1);
  save('basket'); updateBadge();
  renderBasket(document.getElementById('content'));
}

function clearBasket() {
  if (!confirm('Clear all items from basket?')) return;
  S.basket = [];
  save('basket'); updateBadge();
  renderBasket(document.getElementById('content'));
}

function confirmPurchase() {
  if (!S.basket.length) return;
  const total = S.basket.reduce((s, i) => s + (i.price * (i.count || 1)), 0);
  S.history.unshift({ date: new Date().toISOString(), items: [...S.basket], total, mealPlan: S.mealPlan ? [...S.mealPlan] : null });
  save('history');
  S.basket = [];
  save('basket'); updateBadge();
  toast('Purchase confirmed! Added to history.', 'success');
  renderBasket(document.getElementById('content'));
}

// ── Calendar ─────────────────────────────────────────────────────────────────
function renderCalendar(el) {
  if (!S.mealPlan || !S.mealPlan.length) {
    el.innerHTML = `<div class="empty-state"><i class="fa-solid fa-calendar-days"></i><p>No meal plan yet</p>
      <button class="btn-primary mt-2" onclick="location.hash='#/planner'"><i class="fa-solid fa-utensils"></i> Create Meal Plan</button></div>`;
    return;
  }

  const days = [...new Set(S.mealPlan.map(m => m.Day))];
  el.innerHTML = `
    <div class="flex-between mb-3">
      <span class="text-muted text-sm">${days.length}-day meal plan</span>
      <button class="btn-secondary" onclick="exportICS()"><i class="fa-solid fa-download"></i> Export .ics</button>
    </div>
    <div class="cal-grid">
      ${days.map(day => {
        const meals = S.mealPlan.filter(m => m.Day === day);
        return `<div class="cal-day">
          <div class="cal-day-header">${day}</div>
          ${meals.map(m => `<div class="cal-meal">
            <div class="cal-meal-slot">${m.Meal || ''}</div>
            <div class="cal-meal-name">${m.name || 'Unknown'}</div>
            <div class="cal-meal-cals">${Math.round(m.calories || 0)} kcal</div>
          </div>`).join('')}
        </div>`;
      }).join('')}
    </div>
  `;
}

function exportICS() {
  if (!S.mealPlan) return;
  const url = `/api/calendar/export?plan_json=${encodeURIComponent(JSON.stringify(S.mealPlan))}`;
  window.open(url, '_blank');
  toast('Calendar file downloading', 'success');
}

// ── Recipes ──────────────────────────────────────────────────────────────────
function renderRecipes(el) {
  el.innerHTML = `
    <div class="tabs">
      <button class="tab active" data-tab="import"><i class="fa-solid fa-link"></i> Import</button>
      <button class="tab" data-tab="submit"><i class="fa-solid fa-plus"></i> Submit</button>
      <button class="tab" data-tab="browse"><i class="fa-solid fa-book-open"></i> Your Recipes</button>
    </div>
    <div id="recipe-tab-content"></div>
  `;
  const tabs = el.querySelectorAll('.tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      if (tab.dataset.tab === 'submit') renderRecipeSubmit();
      else if (tab.dataset.tab === 'browse') renderRecipeBrowse();
      else renderRecipeImport();
    });
  });
  renderRecipeImport();
}

function renderRecipeImport() {
  document.getElementById('recipe-tab-content').innerHTML = `
    <div class="card">
      <div class="card-header"><i class="fa-brands fa-youtube" style="color:#ff0000"></i><h3>Import from YouTube</h3></div>
      <p class="hint">Paste any YouTube video URL — the transcript will be analysed and the recipe extracted automatically.</p>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group" style="flex:1"><label>YouTube URL</label>
          <input type="text" id="import-yt-url" placeholder="https://www.youtube.com/watch?v=...">
        </div>
        <button class="btn-primary" onclick="importFromYouTube()" id="btn-import-yt">
          <i class="fa-solid fa-download"></i> Extract Recipe
        </button>
      </div>
    </div>
    <div class="card" style="margin-top:1rem">
      <div class="card-header"><i class="fa-solid fa-globe"></i><h3>Import from URL</h3></div>
      <p class="hint">Paste a recipe page URL (AllRecipes, Food.com, any site with structured recipe data).</p>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group" style="flex:1"><label>Recipe Page URL</label>
          <input type="text" id="import-url" placeholder="https://www.allrecipes.com/recipe/...">
        </div>
        <button class="btn-primary" onclick="importFromUrl()" id="btn-import-url">
          <i class="fa-solid fa-download"></i> Extract Recipe
        </button>
      </div>
    </div>
  `;
}

function _fillRecipeForm(recipe) {
  // Switch to Submit tab and pre-fill the form
  const tabs = document.querySelectorAll('.tab');
  tabs.forEach(t => t.classList.remove('active'));
  tabs.forEach(t => { if (t.dataset.tab === 'submit') t.classList.add('active'); });
  renderRecipeSubmit();
  if (recipe.name)         document.getElementById('r-name').value       = recipe.name;
  if (recipe.category)     document.getElementById('r-cat').value        = recipe.category;
  if (recipe.prep_time)    document.getElementById('r-time').value       = recipe.prep_time;
  if (recipe.calories)     document.getElementById('r-cal').value        = Math.round(recipe.calories);
  if (recipe.protein)      document.getElementById('r-prot').value       = Math.round(recipe.protein);
  if (recipe.carbs)        document.getElementById('r-carb').value       = Math.round(recipe.carbs);
  if (recipe.fat)          document.getElementById('r-fat').value        = Math.round(recipe.fat);
  if (recipe.ingredients)  document.getElementById('r-ing').value        = Array.isArray(recipe.ingredients) ? recipe.ingredients.join(', ') : recipe.ingredients;
  if (recipe.instructions) document.getElementById('r-inst').value       = recipe.instructions;
  if (recipe.source_url)   document.getElementById('r-source-url').value = recipe.source_url;
  // Reset star picker for imported recipes (no pre-existing rating)
  const imp = Math.round(recipe.rating || 0);
  if (imp > 0) _setRecipeRating(imp);
  toast(`Recipe "${recipe.name || 'imported'}" loaded — review and submit!`, 'success');
}

async function importFromYouTube() {
  const url = document.getElementById('import-yt-url')?.value?.trim();
  if (!url) { toast('Paste a YouTube URL first', 'error'); return; }
  const btn = document.getElementById('btn-import-yt');
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Extracting…';
  try {
    const res = await api.post('/api/recipes/import-youtube', { url, api_key: S.settings.groqKey });
    if (res.ok) _fillRecipeForm(res.recipe);
    else toast(res.error || 'Extraction failed', 'error');
  } catch (e) { toast('Network error', 'error'); }
  btn.disabled = false;
  btn.innerHTML = '<i class="fa-solid fa-download"></i> Extract Recipe';
}

async function importFromUrl() {
  const url = document.getElementById('import-url')?.value?.trim();
  if (!url) { toast('Paste a recipe URL first', 'error'); return; }
  const btn = document.getElementById('btn-import-url');
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Extracting…';
  try {
    const res = await api.post('/api/recipes/import-url', { url, api_key: S.settings.groqKey });
    if (res.ok) _fillRecipeForm(res.recipe);
    else toast(res.error || 'Extraction failed', 'error');
  } catch (e) { toast('Network error', 'error'); }
  btn.disabled = false;
  btn.innerHTML = '<i class="fa-solid fa-download"></i> Extract Recipe';
}

function renderRecipeSubmit() {
  document.getElementById('recipe-tab-content').innerHTML = `
    <div class="card">
      <div class="card-header"><i class="fa-solid fa-plus"></i><h3>Submit a New Recipe</h3></div>
      <div class="form-group"><label>Recipe Name</label><input type="text" id="r-name" placeholder="e.g. Chicken Stir Fry"></div>
      <div class="form-row">
        <div class="form-group"><label>Category</label>
          <select id="r-cat"><option>Main Dish</option><option>Breakfast</option><option>Snack</option><option>Dessert</option><option>Beverage</option><option>Salad</option><option>Soup</option></select>
        </div>
        <div class="form-group"><label>Prep Time (min)</label><input type="number" id="r-time" value="30" min="5" max="300"></div>
        <div class="form-group">
          <label>Your Rating <span class="hint">(0 – 5, supports decimals)</span></label>
          <div style="display:flex;align-items:center;gap:10px;margin-top:6px">
            <div id="r-star-display" style="font-size:1.3rem;letter-spacing:1px;color:#f59e0b;min-width:90px">☆☆☆☆☆</div>
            <span id="r-rating-label" style="font-size:.85rem;font-weight:600;color:var(--text);min-width:32px">0</span>
          </div>
          <input type="range" id="r-rating" min="0" max="5" step="0.5" value="0"
            oninput="_updateStarDisplay(this.value)"
            style="width:100%;margin-top:6px;accent-color:var(--primary)">
          <div style="display:flex;justify-content:space-between;font-size:.7rem;color:var(--text-light);margin-top:2px">
            <span>0</span><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span>
          </div>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Calories</label><input type="number" id="r-cal" value="400"></div>
        <div class="form-group"><label>Protein (g)</label><input type="number" id="r-prot" value="25"></div>
        <div class="form-group"><label>Carbs (g)</label><input type="number" id="r-carb" value="40"></div>
        <div class="form-group"><label>Fat (g)</label><input type="number" id="r-fat" value="15"></div>
      </div>
      <div class="form-group"><label>Ingredients <span class="hint">(comma-separated)</span></label><textarea id="r-ing" rows="3" placeholder="chicken breast, soy sauce, garlic, bell pepper..."></textarea></div>
      <div class="form-group"><label>Instructions</label><textarea id="r-inst" rows="4" placeholder="Step-by-step instructions..."></textarea></div>
      <div class="form-group"><label>Source URL <span class="hint">(YouTube or website — optional, kept as a link on the card)</span></label><input type="url" id="r-source-url" placeholder="https://www.youtube.com/watch?v=... or https://allrecipes.com/..."></div>
      <button class="btn-primary" onclick="submitRecipe()"><i class="fa-solid fa-paper-plane"></i> Submit Recipe</button>
    </div>
  `;
}

function _updateStarDisplay(val) {
  val = parseFloat(val) || 0;
  const label = document.getElementById('r-rating-label');
  const display = document.getElementById('r-star-display');
  if (label) label.textContent = val.toFixed(1);
  if (display) {
    const full = Math.floor(val);
    const half = (val - full) >= 0.5 ? 1 : 0;
    const empty = 5 - full - half;
    display.textContent = '★'.repeat(full) + (half ? '½' : '') + '☆'.repeat(empty);
  }
}
// Alias kept for backward compat (edit pre-fill)
function _setRecipeRating(val) {
  const slider = document.getElementById('r-rating');
  if (slider) { slider.value = val; _updateStarDisplay(val); }
}

async function submitRecipe(editIdx = null) {
  const name = document.getElementById('r-name')?.value?.trim();
  if (!name) { toast('Recipe name is required', 'error'); return; }
  const payload = {
    name,
    category:     document.getElementById('r-cat')?.value          || 'Main Dish',
    ingredients:  document.getElementById('r-ing')?.value          || '',
    instructions: document.getElementById('r-inst')?.value         || '',
    calories:    +document.getElementById('r-cal')?.value          || 400,
    protein:     +document.getElementById('r-prot')?.value         || 25,
    carbs:       +document.getElementById('r-carb')?.value         || 40,
    fat:         +document.getElementById('r-fat')?.value          || 15,
    prep_time:   +document.getElementById('r-time')?.value         || 30,
    rating:      +document.getElementById('r-rating')?.value       || 4.0,
    source_url:   document.getElementById('r-source-url')?.value?.trim() || '',
  };
  try {
    let res;
    if (editIdx !== null) {
      // Update existing recipe
      res = await fetch(`/api/recipes/user/${editIdx}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(r => r.json());
      if (res.ok) { toast('Recipe updated!', 'success'); renderRecipeBrowse(); document.querySelector('.tab[data-tab="browse"]')?.click(); }
    } else {
      res = await api.post('/api/recipes/submit', payload);
      if (res.ok) { toast('Recipe saved!', 'success'); document.getElementById('r-name').value = ''; }
    }
    if (!res.ok) toast(res.error || 'Failed', 'error');
  } catch (e) { toast('Network error', 'error'); }
}

async function renderRecipeBrowse() {
  const c = document.getElementById('recipe-tab-content');
  c.innerHTML = `<div class="loading-overlay"><div class="spinner"></div><div>Loading recipes...</div></div>`;
  try {
    const res = await api.get('/api/recipes/user');
    const recipes = res.recipes || [];
    if (!recipes.length) {
      c.innerHTML = `<div class="empty-state"><i class="fa-solid fa-book-open"></i><p>No user recipes yet. Submit one!</p></div>`;
      return;
    }
    c.innerHTML = `<div class="card-grid">${recipes.map((r, idx) => {
      const ratingVal = r.rating != null && r.rating > 0 ? r.rating : null;
      const stars = ratingVal ? ('★'.repeat(Math.round(ratingVal)).padEnd(5,'☆').slice(0,5) + ` ${ratingVal.toFixed(1)}`) : '—';
      const hasLink = r.source_url && r.source_url.trim();
      const isYT = hasLink && r.source_url.includes('youtu');
      return `
      <div class="recipe-card" style="position:relative">
        <!-- Custom badge -->
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <span style="font-size:.7rem;font-weight:600;padding:2px 8px;border-radius:9999px;background:var(--primary-light);color:var(--primary)">
            <i class="fa-solid fa-user" style="margin-right:4px"></i>Custom
          </span>
          <div style="display:flex;gap:4px">
            <button onclick="editRecipe(${idx})" title="Edit recipe"
              style="border:none;background:none;cursor:pointer;color:var(--text-light);font-size:.8rem;padding:2px 6px;border-radius:6px;transition:background .15s"
              onmouseover="this.style.background='var(--surface-alt)'" onmouseout="this.style.background='none'">
              <i class="fa-solid fa-pen"></i>
            </button>
            <button onclick="deleteRecipe(${idx})" title="Delete recipe"
              style="border:none;background:none;cursor:pointer;color:#ef4444;font-size:.8rem;padding:2px 6px;border-radius:6px;transition:background .15s"
              onmouseover="this.style.background='#fee2e2'" onmouseout="this.style.background='none'">
              <i class="fa-solid fa-trash"></i>
            </button>
          </div>
        </div>
        <h4 style="margin:0 0 6px;font-size:.95rem;font-weight:600">${r.name || 'Untitled'}</h4>
        <div class="recipe-meta">
          <span><i class="fa-solid fa-tag"></i> ${r.category || 'Main'}</span>
          <span><i class="fa-solid fa-clock"></i> ${r.prep_time || 30} min</span>
          <span><i class="fa-solid fa-star" style="color:#f59e0b"></i> ${stars}</span>
        </div>
        <div class="recipe-meta" style="margin-top:4px">
          <span><i class="fa-solid fa-fire"></i> ${Math.round(r.calories || 0)} kcal</span>
          <span>${Math.round(r.protein || 0)}g P</span>
          <span>${Math.round(r.carbs || 0)}g C</span>
          <span>${Math.round(r.fat || 0)}g F</span>
        </div>
        ${r.ingredients ? `<p class="text-sm text-muted mt-1" style="line-height:1.4">${r.ingredients.substring(0, 120)}${r.ingredients.length > 120 ? '…' : ''}</p>` : ''}
        ${hasLink ? `
        <a href="${r.source_url}" target="_blank" rel="noopener"
           style="display:inline-flex;align-items:center;gap:5px;margin-top:8px;font-size:.75rem;font-weight:600;
                  color:${isYT ? '#ef4444' : 'var(--primary)'};text-decoration:none;border:1px solid ${isYT ? '#fecaca' : 'var(--primary-light)'};
                  border-radius:9999px;padding:2px 10px;background:${isYT ? '#fee2e220' : 'var(--primary-light)'}">
          <i class="fa-${isYT ? 'brands fa-youtube' : 'solid fa-arrow-up-right-from-square'}"></i>
          ${isYT ? 'Watch on YouTube' : 'View source'}
        </a>` : ''}
      </div>`;
    }).join('')}</div>`;
  } catch (e) { c.innerHTML = `<div class="empty-state"><p>Failed to load recipes</p></div>`; }
}

async function deleteRecipe(idx) {
  if (!confirm('Delete this recipe? This cannot be undone.')) return;
  try {
    const res = await fetch(`/api/recipes/user/${idx}`, { method: 'DELETE' }).then(r => r.json());
    if (res.ok) { toast('Recipe deleted', 'success'); renderRecipeBrowse(); }
    else toast(res.error || 'Failed to delete', 'error');
  } catch (e) { toast('Network error', 'error'); }
}

function editRecipe(idx) {
  // Switch to Submit tab and pre-fill form with existing data
  fetch('/api/recipes/user').then(r => r.json()).then(res => {
    const recipes = res.recipes || [];
    const r = recipes[idx];
    if (!r) return;
    // Switch to submit tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector('.tab[data-tab="submit"]')?.classList.add('active');
    renderRecipeSubmit();
    // Pre-fill after render
    setTimeout(() => {
      if (r.name)         document.getElementById('r-name').value         = r.name;
      if (r.category)     document.getElementById('r-cat').value          = r.category;
      if (r.prep_time)    document.getElementById('r-time').value         = r.prep_time;
      if (r.calories)     document.getElementById('r-cal').value          = Math.round(r.calories);
      if (r.protein)      document.getElementById('r-prot').value         = Math.round(r.protein);
      if (r.carbs)        document.getElementById('r-carb').value         = Math.round(r.carbs);
      if (r.fat)          document.getElementById('r-fat').value          = Math.round(r.fat);
      if (r.ingredients)  document.getElementById('r-ing').value          = r.ingredients;
      if (r.instructions) document.getElementById('r-inst').value         = r.instructions;
      if (r.source_url)   document.getElementById('r-source-url').value   = r.source_url;
      // Set star picker — use stored rating, default 0 (unrated)
      const storedRating = Math.round(r.rating || 0);
      if (storedRating > 0) _setRecipeRating(storedRating);
      else { document.getElementById('r-rating').value = 0; }
      // Change submit button to "Save Changes"
      const btn = document.querySelector('#recipe-tab-content .btn-primary');
      if (btn) {
        btn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Changes';
        btn.onclick = () => submitRecipe(idx);
      }
      toast(`Editing "${r.name}" — make your changes and save`, 'success');
    }, 50);
  });
}

// ── History ──────────────────────────────────────────────────────────────────
function renderHistory(el) {
  if (!S.history.length) {
    el.innerHTML = `<div class="empty-state"><i class="fa-solid fa-clock-rotate-left"></i><p>No purchase history yet</p></div>`;
    return;
  }
  // sync history to server so Dash dashboard can read it
  api.post('/api/history/sync', { history: S.history }).catch(() => {});

  el.innerHTML = S.history.map((h, i) => {
    const d = new Date(h.date);
    return `<div class="history-item">
      <div class="history-header" onclick="this.nextElementSibling.classList.toggle('open')">
        <div>
          <strong>${d.toLocaleDateString()} ${d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</strong>
          <span class="tag" style="margin-left:8px">${h.items?.length || 0} items</span>
        </div>
        <span style="font-weight:700;color:var(--primary)">&euro;${(h.total || 0).toFixed(2)}</span>
      </div>
      <div class="history-body">
        <div class="table-wrap">
          <table><thead><tr><th>Product</th><th>Count</th><th>Price</th></tr></thead><tbody>
            ${(h.items || []).map(it => `<tr><td>${it.name}</td><td>${it.count || 1}</td><td>&euro;${((it.price||0)*(it.count||1)).toFixed(2)}</td></tr>`).join('')}
          </tbody></table>
        </div>
      </div>
    </div>`;
  }).join('') + `
    <div style="margin-top:24px">
      <h3 style="font-size:.9rem;font-weight:600;margin-bottom:8px;color:var(--text-light)">
        <i class="fa-solid fa-chart-line" style="margin-right:6px;color:var(--primary)"></i>Spending Analytics
      </h3>
      <iframe id="dash-history" src="/dash/history?t=${Date.now()}"
        style="width:100%;height:480px;border:none;border-radius:6px;background:#fff" loading="lazy"></iframe>
    </div>`;
}

// ── Fridge → Recipe ───────────────────────────────────────────────────────────

function renderFridge(el) {
  el.innerHTML = `
    <div style="max-width:860px;margin:0 auto">
      <div class="card" style="margin-bottom:20px">
        <h2 style="margin:0 0 8px;font-size:1.05rem"><i class="fa-solid fa-refrigerator" style="color:var(--primary);margin-right:8px"></i>What's in My Fridge?</h2>
        <p class="text-muted text-sm" style="margin:0 0 16px">Enter the ingredients you have and we'll suggest matching recipes from our database — or generate a new one just for you.</p>
        <div id="fridge-tags" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;min-height:32px"></div>
        <div style="display:flex;gap:8px">
          <input type="text" id="fridge-input" placeholder="Type an ingredient and press Enter (e.g. chicken, garlic, tomatoes…)" style="flex:1">
          <button class="btn-primary" id="btn-fridge-add"><i class="fa-solid fa-plus"></i></button>
        </div>
        <div style="margin-top:14px;display:flex;gap:8px">
          <button class="btn-primary" id="btn-fridge-search" style="flex:1"><i class="fa-solid fa-wand-magic-sparkles"></i> Find Recipes</button>
          <button class="btn-secondary" id="btn-fridge-clear">Clear</button>
        </div>
      </div>
      <div id="fridge-results"></div>
    </div>`;

  const fridgeIngredients = [];

  function addIngredient() {
    const inp = document.getElementById('fridge-input');
    const raw = inp.value.trim();
    if (!raw) return;
    raw.split(',').map(s => s.trim()).filter(Boolean).forEach(item => {
      if (!fridgeIngredients.includes(item.toLowerCase())) {
        fridgeIngredients.push(item.toLowerCase());
      }
    });
    inp.value = '';
    renderTags();
  }

  function renderTags() {
    const container = document.getElementById('fridge-tags');
    if (!container) return;
    container.innerHTML = fridgeIngredients.map((ing, i) =>
      `<span class="chip" style="cursor:default">
        ${ing}
        <button onclick="this.parentElement.remove();fridgeIngredients_remove(${i})" style="background:none;border:none;cursor:pointer;padding:0 0 0 6px;color:var(--text-light)">&times;</button>
      </span>`
    ).join('');
  }

  // Expose remove helper (scoped via closure workaround)
  window._fridgeRemove = (i) => {
    fridgeIngredients.splice(i, 1);
    renderTags();
  };

  // Patch tag HTML to use window helper
  function renderTagsSafe() {
    const container = document.getElementById('fridge-tags');
    if (!container) return;
    container.innerHTML = fridgeIngredients.map((ing, i) =>
      `<span class="chip" style="cursor:default;display:inline-flex;align-items:center;gap:4px">
        ${ing}
        <span onclick="window._fridgeRemove(${i})" style="cursor:pointer;opacity:.6;font-weight:700">&times;</span>
      </span>`
    ).join('');
  }

  function addIngredientSafe() {
    const inp = document.getElementById('fridge-input');
    const raw = inp?.value?.trim();
    if (!raw) return;
    raw.split(',').map(s => s.trim()).filter(Boolean).forEach(item => {
      const key = item.toLowerCase();
      if (!fridgeIngredients.includes(key)) fridgeIngredients.push(key);
    });
    inp.value = '';
    renderTagsSafe();
  }

  window._fridgeRemove = (i) => { fridgeIngredients.splice(i, 1); renderTagsSafe(); };

  document.getElementById('btn-fridge-add')?.addEventListener('click', addIngredientSafe);
  document.getElementById('fridge-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') addIngredientSafe(); });
  document.getElementById('btn-fridge-clear')?.addEventListener('click', () => {
    fridgeIngredients.length = 0;
    renderTagsSafe();
    document.getElementById('fridge-results').innerHTML = '';
  });

  document.getElementById('btn-fridge-search')?.addEventListener('click', async () => {
    if (!fridgeIngredients.length) { toast('Add at least one ingredient first', 'error'); return; }
    if (!S.settings.groqKey) { toast('Set your Groq API key in Settings', 'error'); return; }

    const results = document.getElementById('fridge-results');
    results.innerHTML = `<div class="card" style="text-align:center;padding:32px">
      <span class="spinner" style="display:inline-block;margin-bottom:12px"></span>
      <p class="text-muted">Searching ${fridgeIngredients.length} ingredient(s)…</p>
    </div>`;

    try {
      const res = await api.post('/api/fridge/suggest', {
        ingredients: fridgeIngredients,
        api_key: S.settings.groqKey,
      });

      if (!res.ok) { results.innerHTML = `<div class="card"><p class="text-muted">${res.error || 'Error occurred.'}</p></div>`; return; }

      if (res.path === 'database') {
        results.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
            <span class="tag" style="background:var(--primary-light);color:var(--primary)"><i class="fa-solid fa-database"></i> Found in your recipe database</span>
            <span class="text-muted text-sm">Top match score: ${(res.tfidf_score * 100).toFixed(0)}%</span>
          </div>
          ${res.recipes.map(r => `
            <div class="card" style="margin-bottom:14px">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
                <div>
                  <h3 style="margin:0 0 4px;font-size:1rem">${r.name}</h3>
                  <span class="tag">${r.category || 'Recipe'}</span>
                </div>
                <div style="text-align:right;font-size:.85rem;color:var(--text-light)">
                  ${r.calories ? `<div>${Math.round(r.calories)} kcal</div>` : ''}
                  ${r.prep_time ? `<div>${r.prep_time} min</div>` : ''}
                </div>
              </div>
              ${r.matched_fridge?.length ? `
                <p class="text-sm" style="margin:10px 0 4px"><strong>Uses from your fridge:</strong>
                  ${r.matched_fridge.map(i => `<span class="chip" style="background:var(--primary-light);color:var(--primary)">${i}</span>`).join(' ')}
                </p>` : ''}
              ${r.ingredients?.length ? `
                <details style="margin-top:8px">
                  <summary class="text-sm text-muted" style="cursor:pointer">All ingredients (${r.ingredients.length})</summary>
                  <p class="text-sm" style="margin-top:6px">${r.ingredients.join(', ')}</p>
                </details>` : ''}
            </div>`).join('')}`;
      } else if (res.path === 'generated') {
        const r = res.recipe;
        results.innerHTML = `
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
            <span class="tag" style="background:#ede9fe;color:#6d28d9"><i class="fa-solid fa-wand-magic-sparkles"></i> AI-generated recipe</span>
            <span class="text-muted text-sm">No strong DB match found — Groq created this for you</span>
          </div>
          <div class="card">
            <h3 style="margin:0 0 8px;font-size:1.1rem">${r.name || 'Generated Recipe'}</h3>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;font-size:.85rem;color:var(--text-light)">
              ${r.servings ? `<span><i class="fa-solid fa-users"></i> ${r.servings} servings</span>` : ''}
              ${r.prep_time_minutes ? `<span><i class="fa-solid fa-clock"></i> ${r.prep_time_minutes} min</span>` : ''}
              ${r.estimated_nutrition?.calories ? `<span><i class="fa-solid fa-fire"></i> ~${r.estimated_nutrition.calories} kcal</span>` : ''}
              ${r.estimated_nutrition?.protein_g ? `<span><i class="fa-solid fa-dumbbell"></i> ${r.estimated_nutrition.protein_g}g protein</span>` : ''}
            </div>
            ${r.uses_from_fridge?.length ? `
              <p class="text-sm" style="margin-bottom:8px"><strong>Uses from your fridge:</strong>
                ${r.uses_from_fridge.map(i => `<span class="chip" style="background:var(--primary-light);color:var(--primary)">${i}</span>`).join(' ')}
              </p>` : ''}
            ${r.additional_ingredients?.length ? `
              <p class="text-sm" style="margin-bottom:12px"><strong>You'll also need:</strong> ${r.additional_ingredients.join(', ')}</p>` : ''}
            <details open>
              <summary class="text-sm" style="cursor:pointer;font-weight:600;margin-bottom:8px">Ingredients</summary>
              <ul style="margin:6px 0 0;padding-left:20px;font-size:.9rem">${(r.ingredients || []).map(i => `<li>${i}</li>`).join('')}</ul>
            </details>
            <details open style="margin-top:12px">
              <summary class="text-sm" style="cursor:pointer;font-weight:600;margin-bottom:8px">Instructions</summary>
              <ol style="margin:6px 0 0;padding-left:20px;font-size:.9rem">${(r.instructions || []).map(s => `<li style="margin-bottom:6px">${s}</li>`).join('')}</ol>
            </details>
            ${r.tips ? `<p class="text-sm text-muted" style="margin-top:12px"><i class="fa-solid fa-lightbulb"></i> ${r.tips}</p>` : ''}
          </div>`;
      } else {
        results.innerHTML = `<div class="card"><p class="text-muted">${res.error || 'Could not find or generate a recipe. Try different ingredients.'}</p></div>`;
      }
    } catch (e) {
      results.innerHTML = `<div class="card"><p class="text-muted">Network error: ${e.message}</p></div>`;
    }
  });
}

// ── Nutrition Coach ───────────────────────────────────────────────────────────
let _nutritionChat = [];  // session-only; not persisted

function renderNutrition(el) {
  el.innerHTML = `
    <div class="card" style="max-width:800px;margin:0 auto;display:flex;flex-direction:column;height:calc(100vh - 120px)">
      <div style="padding:20px 24px;border-bottom:1px solid var(--border)">
        <h2 style="margin:0;font-size:1.1rem"><i class="fa-solid fa-apple-whole" style="color:var(--primary);margin-right:8px"></i>Nutrition Coach</h2>
        <p class="text-muted text-sm" style="margin:4px 0 0">Ask about macros, diet programs, weekly meal plans, or food nutrition facts.</p>
      </div>
      <div id="nutrition-messages" style="flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:12px"></div>
      <div style="padding:16px 20px;border-top:1px solid var(--border);display:flex;gap:8px">
        <input type="text" id="nutrition-input" placeholder="e.g. I'm 80kg, 180cm, 30yo male, want to lose weight..." style="flex:1">
        <button class="btn-primary" id="btn-nutrition-send"><i class="fa-solid fa-paper-plane"></i></button>
      </div>
    </div>`;

  renderNutritionMessages();
  document.getElementById('btn-nutrition-send')?.addEventListener('click', sendNutritionMessage);
  document.getElementById('nutrition-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendNutritionMessage(); });
  document.getElementById('nutrition-input')?.focus();
}

function renderNutritionMessages() {
  const c = document.getElementById('nutrition-messages');
  if (!c) return;
  if (!_nutritionChat.length) {
    c.innerHTML = `<div class="text-muted text-sm" style="text-align:center;margin-top:40px">
      <i class="fa-solid fa-apple-whole" style="font-size:2rem;opacity:.3;display:block;margin-bottom:12px"></i>
      Tell me about your goals and I'll build your nutrition program.<br>
      <span style="opacity:.6">e.g. "I'm 75kg, 170cm, 28yo female, moderately active, want to lose weight"</span>
    </div>`;
    return;
  }
  c.innerHTML = _nutritionChat.map(m => {
    const isUser = m.role === 'user';
    return `<div class="chat-msg ${isUser ? 'user' : 'assistant'}">
      <div class="chat-bubble">${m.content.replace(/\n/g, '<br>')}</div>
    </div>`;
  }).join('');
  c.scrollTop = c.scrollHeight;
}

async function sendNutritionMessage() {
  const input = document.getElementById('nutrition-input');
  const msg = input?.value?.trim();
  if (!msg) return;
  if (!S.settings.groqKey) { toast('Set your Groq API key in Settings', 'error'); return; }

  _nutritionChat.push({ role: 'user', content: msg });
  input.value = '';
  renderNutritionMessages();

  // Thinking indicator
  const c = document.getElementById('nutrition-messages');
  const thinking = document.createElement('div');
  thinking.className = 'chat-msg assistant';
  thinking.innerHTML = '<div class="chat-bubble"><span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block"></span> Thinking…</div>';
  c?.appendChild(thinking);
  c.scrollTop = c.scrollHeight;

  const history = _nutritionChat.slice(-20).map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content }));

  try {
    const res = await api.post('/api/nutrition-chat', {
      message: msg,
      history: history.slice(0, -1),
      api_key: S.settings.groqKey,
    });
    thinking.remove();
    if (res.ok) {
      _nutritionChat.push({ role: 'assistant', content: res.reply || 'No response' });
      // If agent returned a weekly plan, offer import
      if (res.nutrition_plan?.length) {
        _nutritionChat.push({
          role: 'assistant',
          content: `📋 Weekly plan generated (${res.nutrition_plan.length} days). You can import it into the Meal Planner — feature coming soon.`
        });
      }
    } else {
      _nutritionChat.push({ role: 'assistant', content: `Error: ${res.error || 'Unknown error'}` });
    }
  } catch (e) {
    thinking.remove();
    _nutritionChat.push({ role: 'assistant', content: `Network error: ${e.message}` });
  }
  renderNutritionMessages();
}

// ── Body Optimizer ────────────────────────────────────────────────────────────

const _bodyMeasurements = JSON.parse(localStorage.getItem('bodyMeasurements') || 'null') || {
  sex: 'male', age: 30, weight_kg: 75, height_cm: 175, activity: 'moderate'
};
// Body Optimizer runtime state — populated after analysis
let _lastNutrientData   = null;
let _lastNutrientMeta   = null;
let _lastSupplements    = null;
let _driDebounceTimer   = null;
let _extendedNutrients  = null;   // LLM-estimated values for the ~13 untracked nutrients
let _bodyCoachHistory   = [];     // [{role, content}] — Body Coach conversation history

// ── Debate chat runtime state ─────────────────────────────────────────────────
const DEBATE_AGENTS = {
  budget:    { emoji: '💰', label: 'Budget Optimizer', color: '#3b82f6', cls: 'budget-bubble'    },
  nutrition: { emoji: '🥗', label: 'Nutritionist',     color: '#10b981', cls: 'nutrition-bubble' },
  moderator: { emoji: '⚖️', label: 'Moderator',        color: '#f59e0b', cls: 'moderator-bubble' },
};
let _debateHistory     = [];
let _debateActiveAgents = new Set(['budget', 'nutrition', 'moderator']);

// Mapping: NUTRIENT_META key → { driKey, toMcgOrMg (converts IU/g to the DRI unit) }
const _NUTRIENT_TO_DRI = {
  vitamin_d_iu:    { driKey: 'vit_d_mcg',   conv: v => +(v / 40).toFixed(1) },  // IU → mcg
  vitamin_b12_mcg: { driKey: 'vit_b12_mcg', conv: v => +v.toFixed(1) },
  magnesium_mg:    { driKey: 'magnesium_mg', conv: v => +v.toFixed(0) },
  zinc_mg:         { driKey: 'zinc_mg',      conv: v => +v.toFixed(1) },
  iron_mg:         { driKey: 'iron_mg',      conv: v => +v.toFixed(1) },
  calcium_mg:      { driKey: 'calcium_mg',   conv: v => +v.toFixed(0) },
  vitamin_c_mg:    { driKey: 'vit_c_mg',     conv: v => +v.toFixed(0) },
  folate_mcg:      { driKey: 'vit_b9_mcg',   conv: v => +v.toFixed(0) },
  vitamin_k_mcg:   { driKey: 'vit_k_mcg',   conv: v => +v.toFixed(0) },
  selenium_mcg:    { driKey: 'selenium_mcg', conv: v => +v.toFixed(1) },
  potassium_mg:    { driKey: 'potassium_mg', conv: v => +v.toFixed(0) },
};

function _parseDose(doseStr) {
  // Returns numeric value from a dose string in its native unit, or null
  if (!doseStr || typeof doseStr !== 'string' || doseStr === 'per DRI') return null;
  const m = doseStr.match(/([\d,]+(?:\.\d+)?)\s*(IU|mcg|mg|g)?/i);
  if (!m) return null;
  let val = parseFloat(m[1].replace(/,/g, ''));
  if ((m[2] || '').toLowerCase() === 'g') val *= 1000; // g → mg
  return isNaN(val) ? null : val;
}

function renderBody(el) {
  el.innerHTML = `
    <div style="display:grid;grid-template-columns:280px 1fr 300px;gap:20px;align-items:start">

      <!-- LEFT: Profile form -->
      <div>
        <div class="card" style="margin-bottom:16px">
          <h3 style="font-size:.9rem;font-weight:700;margin:0 0 12px"><i class="fa-solid fa-user" style="color:var(--primary);margin-right:6px"></i>Your Profile</h3>
          <div class="form-group" style="margin-bottom:10px">
            <label style="font-size:.8rem">Sex</label>
            <select id="body-sex" style="width:100%">
              <option value="male" ${_bodyMeasurements.sex==='male'?'selected':''}>Male</option>
              <option value="female" ${_bodyMeasurements.sex==='female'?'selected':''}>Female</option>
            </select>
          </div>
          <div class="form-group" style="margin-bottom:10px">
            <label style="font-size:.8rem">Age</label>
            <input type="number" id="body-age" value="${_bodyMeasurements.age}" min="15" max="100" style="width:100%">
          </div>
          <div class="form-group" style="margin-bottom:10px">
            <label style="font-size:.8rem">Weight (kg)</label>
            <input type="number" id="body-weight" value="${_bodyMeasurements.weight_kg}" min="30" max="300" step="0.5" style="width:100%">
          </div>
          <div class="form-group" style="margin-bottom:10px">
            <label style="font-size:.8rem">Height (cm)</label>
            <input type="number" id="body-height" value="${_bodyMeasurements.height_cm}" min="100" max="250" style="width:100%">
          </div>
          <div class="form-group" style="margin-bottom:14px">
            <label style="font-size:.8rem">Activity Level</label>
            <select id="body-activity" style="width:100%">
              <option value="sedentary"  ${_bodyMeasurements.activity==='sedentary'?'selected':''}>Sedentary (desk job, no exercise)</option>
              <option value="light"      ${_bodyMeasurements.activity==='light'?'selected':''}>Light (1–2x/week)</option>
              <option value="moderate"   ${_bodyMeasurements.activity==='moderate'?'selected':''}>Moderate (3–4x/week)</option>
              <option value="active"     ${_bodyMeasurements.activity==='active'?'selected':''}>Active (5–6x/week)</option>
              <option value="very_active"${_bodyMeasurements.activity==='very_active'?'selected':''}>Very Active (athlete / physical job)</option>
            </select>
          </div>
          <button class="btn-primary" style="width:100%" id="btn-body-analyze">
            <i class="fa-solid fa-flask"></i> Analyze My Nutrients
          </button>
        </div>

        <!-- Quick stats card -->
        <div class="card" id="body-stats-card" style="display:none">
          <h3 style="font-size:.85rem;font-weight:700;margin:0 0 10px"><i class="fa-solid fa-bolt" style="color:#f59e0b;margin-right:6px"></i>Quick Stats</h3>
          <div id="body-stats-content"></div>
        </div>
      </div>

      <!-- CENTER: Nutrient dashboard -->
      <div>
        <div class="card" id="body-nutrients-card">
          <h3 style="font-size:.9rem;font-weight:700;margin:0 0 4px"><i class="fa-solid fa-chart-bar" style="color:var(--primary);margin-right:6px"></i>Nutrient Coverage</h3>
          <p class="text-sm text-muted" style="margin:0 0 14px">Based on your current meal plan vs. your daily requirements (DRI). Click "Analyze" to update.</p>
          <div id="body-nutrients-content">
            <div class="empty-state" style="min-height:120px"><i class="fa-solid fa-flask"></i><p>Fill in your profile and click Analyze</p></div>
          </div>
        </div>

        <div class="card" id="body-supps-card" style="margin-top:16px;display:none">
          <h3 style="font-size:.9rem;font-weight:700;margin:0 0 4px">
            <i class="fa-solid fa-pills" style="color:#8b5cf6;margin-right:6px"></i>Supplement Recommendations
          </h3>
          <p class="text-sm text-muted" style="margin:0 0 14px">Ranked by gap severity. Blueprint = included in Bryan Johnson's public protocol.</p>
          <div id="body-supps-content"></div>
        </div>

        <div class="card" id="body-dri-card" style="margin-top:16px;display:none">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:4px">
            <h3 style="font-size:.9rem;font-weight:700;margin:0">
              <i class="fa-solid fa-table-list" style="color:#059669;margin-right:6px"></i>Your Full USDA DRI Targets
            </h3>
            <button id="btn-estimate-nutrients" class="btn-secondary btn-sm" onclick="estimateMissingNutrients()" title="Use Groq AI to estimate Vitamin A, B1-B7, Choline, Copper, Iodine, Manganese, Phosphorus from your meal ingredients">
              <i class="fa-solid fa-wand-magic-sparkles"></i> Estimate missing with AI
            </button>
          </div>
          <p class="text-sm text-muted" style="margin:0 0 14px">Daily requirements personalised to your age, sex, weight and activity level.
            <span id="dri-estimate-note" style="display:none;margin-left:6px;color:#f59e0b;font-size:.72rem">
              <i class="fa-solid fa-triangle-exclamation"></i> Cells marked <strong>~</strong> are AI estimates, not measured values.
            </span>
          </p>
          <div id="body-dri-content"></div>
        </div>
      </div>

      <!-- RIGHT: Health news feed -->
      <div>
        <div class="card" style="position:sticky;top:16px">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
            <h3 style="font-size:.9rem;font-weight:700;margin:0"><i class="fa-solid fa-newspaper" style="color:var(--primary);margin-right:6px"></i>Health & Longevity News</h3>
            <div style="display:flex;gap:6px;align-items:center">
              <button class="btn-icon" id="btn-news-refresh" title="Refresh news feed"><i class="fa-solid fa-rotate"></i></button>
              <button class="btn-primary" id="btn-news-ingest" style="font-size:.7rem;padding:4px 10px" title="Re-index articles into vector store"><i class="fa-solid fa-database"></i> Ingest</button>
            </div>
          </div>
          <p class="text-sm text-muted" style="margin:0 0 10px">Huberman Lab · Peter Attia · FoundMyFitness · Lifespan.io · +8 sources</p>
          <!-- Trend signals -->
          <div id="news-trends-strip" style="margin-bottom:10px;display:none"></div>
          <!-- RAG query bar -->
          <div style="margin-bottom:10px">
            <div style="display:flex;gap:6px">
              <input type="text" id="news-query-input" placeholder="Ask the research… e.g. 'what does evidence say about magnesium and sleep?'" style="flex:1;font-size:.75rem;padding:6px 10px">
              <button class="btn-primary" id="btn-news-query" style="white-space:nowrap;font-size:.75rem;padding:6px 10px"><i class="fa-solid fa-magnifying-glass"></i> Ask</button>
            </div>
            <div id="news-query-answer" style="display:none;margin-top:8px;padding:10px;background:var(--bg);border-radius:6px;border-left:3px solid var(--primary)">
              <div id="news-answer-text" class="text-sm" style="line-height:1.5;white-space:pre-wrap"></div>
              <div id="news-answer-sources" style="margin-top:8px"></div>
            </div>
            <div id="news-rag-status" class="text-muted" style="font-size:.65rem;margin-top:4px"></div>
          </div>
          <div id="body-news-feed" style="max-height:calc(100vh - 300px);overflow-y:auto">
            <div class="loading-overlay" style="position:relative;min-height:80px"><div class="spinner"></div></div>
          </div>
        </div>
      </div>

    </div>

    <!-- AI COACH — full-width panel: two sub-tabs (Body Coach | Nutrition Specialist) -->
    <div class="card" id="body-coach-card" style="margin-top:20px">

      <!-- Sub-tab headers -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;border-bottom:1px solid var(--border);padding-bottom:10px">
        <div style="display:flex;gap:4px">
          <button id="coach-tab-body" onclick="_switchCoachTab('body')"
            style="font-size:.8rem;font-weight:600;padding:5px 14px;border-radius:9999px;border:1px solid var(--primary);background:var(--primary);color:#fff;cursor:pointer;transition:all .15s">
            <i class="fa-solid fa-dna"></i> Body Coach
          </button>
          <button id="coach-tab-nutrition" onclick="_switchCoachTab('nutrition')"
            style="font-size:.8rem;font-weight:600;padding:5px 14px;border-radius:9999px;border:1px solid var(--border);background:transparent;color:var(--text-light);cursor:pointer;transition:all .15s">
            <i class="fa-solid fa-apple-whole"></i> Nutrition Specialist
          </button>
        </div>
        <button class="btn-icon" title="Clear conversation" onclick="_bodyCoachClear()">
          <i class="fa-solid fa-broom"></i>
        </button>
      </div>

      <!-- Sub-tab descriptions -->
      <div id="coach-desc-body" style="font-size:.75rem;color:var(--text-light);margin-bottom:10px">
        <i class="fa-solid fa-circle-info" style="margin-right:4px;color:var(--primary)"></i>
        Knows <strong>your real nutrient gaps &amp; supplement recommendations</strong> — run Analyze first for full context.
        Can suggest Amazon supplement links and Mercadona products.
      </div>
      <div id="coach-desc-nutrition" style="font-size:.75rem;color:var(--text-light);margin-bottom:10px;display:none">
        <i class="fa-solid fa-circle-info" style="margin-right:4px;color:#10b981"></i>
        Full <strong>Nutrition Specialist AI</strong> — macros, keto/Mediterranean/IF programs, weekly meal plans, food lookups.
      </div>

      <!-- Message thread -->
      <div id="body-coach-messages" style="max-height:360px;overflow-y:auto;margin-bottom:10px;display:flex;flex-direction:column;gap:8px">
        <div class="text-sm text-muted" style="text-align:center;padding:24px 0;color:var(--text-light)">
          <i class="fa-solid fa-robot" style="font-size:1.8rem;display:block;margin-bottom:8px;color:var(--border)"></i>
          <span id="coach-placeholder-text">Run "Analyze My Nutrients" first, then ask about your gaps, supplements, or meal improvements.</span>
        </div>
      </div>

      <!-- Input row -->
      <div style="display:flex;gap:8px">
        <input type="text" id="body-coach-input"
               placeholder="e.g. Why am I low on Vitamin D? What supplement should I take?"
               style="flex:1;font-size:.82rem"
               onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendBodyCoachMessage();}">
        <button class="btn-primary" id="btn-body-coach-send" onclick="sendBodyCoachMessage()" style="white-space:nowrap">
          <i class="fa-solid fa-paper-plane"></i> Send
        </button>
      </div>
    </div>
  `;

  // Wire up buttons
  document.getElementById('btn-body-analyze')?.addEventListener('click', runBodyAnalysis);
  document.getElementById('btn-news-refresh')?.addEventListener('click', () => loadBodyNews(true));
  document.getElementById('btn-news-ingest')?.addEventListener('click', triggerNewsIngest);
  document.getElementById('btn-news-query')?.addEventListener('click', queryNews);
  document.getElementById('news-query-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') queryNews(); });

  // Live DRI recalculation — fires 400 ms after any profile field change
  ['body-sex','body-age','body-weight','body-height','body-activity'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const handler = () => {
      clearTimeout(_driDebounceTimer);
      // Read current values immediately (for the instant TDEE update)
      const mNow = {
        sex:       document.getElementById('body-sex')?.value      || 'male',
        age:       +document.getElementById('body-age')?.value     || 30,
        weight_kg: +document.getElementById('body-weight')?.value  || 75,
        height_cm: +document.getElementById('body-height')?.value  || 175,
        activity:  document.getElementById('body-activity')?.value || 'moderate',
      };
      // Update Quick Stats (BMI + TDEE) immediately — no network call needed
      renderBodyStats(mNow);
      _driDebounceTimer = setTimeout(async () => {
        // After debounce, re-fetch the full DRI table (protein, fiber targets, etc.)
        const m = {
          sex:       document.getElementById('body-sex')?.value      || 'male',
          age:       +document.getElementById('body-age')?.value     || 30,
          weight_kg: +document.getElementById('body-weight')?.value  || 75,
          height_cm: +document.getElementById('body-height')?.value  || 175,
          activity:  document.getElementById('body-activity')?.value || 'moderate',
        };
        try {
          const driRes = await fetch(
            `/api/body/dri?sex=${m.sex}&age=${m.age}&weight_kg=${m.weight_kg}&height_cm=${m.height_cm}&activity=${m.activity}`
          ).then(r => r.json());
          if (driRes.ok) {
            renderFullDRI(driRes, _lastNutrientData, _lastSupplements);
            // Update the nutrient bars with the new per-person DRI targets (vary by sex + age)
            if (_lastNutrientData && driRes.micronutrient_dri) {
              _lastNutrientData = { ..._lastNutrientData, dri: driRes.micronutrient_dri };
              // Recompute coverage_pct against the new DRI
              const newCoverage = {};
              const intake = _lastNutrientData.daily_intake || {};
              for (const key of Object.keys(driRes.micronutrient_dri)) {
                const req = driRes.micronutrient_dri[key] || 1;
                newCoverage[key] = Math.min(100, ((intake[key] || 0) / req) * 100);
              }
              _lastNutrientData = { ..._lastNutrientData, coverage_pct: newCoverage };
              renderNutrientBars(_lastNutrientData, _lastNutrientMeta);
            }
          }
        } catch (_) {}
      }, 400);
    };
    el.addEventListener('change', handler);
    el.addEventListener('input',  handler);
  });

  // Load news + check RAG status immediately
  loadBodyNews(false);
  checkRagStatus();
}

async function triggerNewsIngest() {
  const btn = document.getElementById('btn-news-ingest');
  const statusEl = document.getElementById('news-rag-status');
  if (!btn) return;
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Ingesting…';
  if (statusEl) statusEl.textContent = 'Ingesting articles into vector store…';
  try {
    const res = await api.post('/api/body/news/ingest', { api_key: S.settings.groqKey });
    if (res.ok) {
      if (statusEl) statusEl.textContent = `✓ Ingested — ${res.chunks_ingested ?? '?'} chunks indexed (${res.chunks ?? '?'} total in store)`;
      checkRagStatus();
    } else {
      if (statusEl) statusEl.textContent = `✗ Ingest failed: ${res.error}`;
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = `✗ Ingest error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-solid fa-database"></i> Ingest';
  }
}

async function loadBodyNews(forceRefresh) {
  const feed = document.getElementById('body-news-feed');
  if (!feed) return;
  if (forceRefresh) feed.innerHTML = '<div class="loading-overlay" style="position:relative;min-height:80px"><div class="spinner"></div></div>';
  try {
    const url = forceRefresh ? '/api/body/news?refresh=true' : '/api/body/news';
    const res = await fetch(url).then(r => r.json());
    const articles = res.articles || [];
    if (!articles.length) {
      feed.innerHTML = '<p class="text-sm text-muted" style="padding:8px">No articles found. Try refreshing.</p>';
      return;
    }
    feed.innerHTML = articles.map(a => `
      <div style="padding:10px 0;border-bottom:1px solid var(--border);last-child:border-none">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
          <span style="font-size:.65rem;font-weight:600;padding:2px 6px;border-radius:9999px;background:var(--primary);color:#fff;white-space:nowrap">${a.source || 'Web'}</span>
          ${a.date ? `<span class="text-muted" style="font-size:.65rem">${a.date.substring(0,16)}</span>` : ''}
        </div>
        <a href="${a.url || '#'}" target="_blank" style="font-size:.8rem;font-weight:600;color:var(--text);text-decoration:none;line-height:1.3;display:block;margin-bottom:4px">${a.title || ''}</a>
        ${a.summary ? `<p style="font-size:.72rem;color:var(--text-light);margin:0;line-height:1.4">${a.summary.substring(0,160)}…</p>` : ''}
      </div>
    `).join('');
  } catch (e) {
    feed.innerHTML = `<p class="text-sm" style="color:var(--error);padding:8px">Failed to load news: ${e.message}</p>`;
  }
}

async function runBodyAnalysis() {
  const btn = document.getElementById('btn-body-analyze');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analyzing…'; }

  // Save measurements to localStorage
  _bodyMeasurements.sex        = document.getElementById('body-sex')?.value      || 'male';
  _bodyMeasurements.age        = +document.getElementById('body-age')?.value     || 30;
  _bodyMeasurements.weight_kg  = +document.getElementById('body-weight')?.value  || 75;
  _bodyMeasurements.height_cm  = +document.getElementById('body-height')?.value  || 175;
  _bodyMeasurements.activity   = document.getElementById('body-activity')?.value || 'moderate';
  localStorage.setItem('bodyMeasurements', JSON.stringify(_bodyMeasurements));

  try {
    const m = _bodyMeasurements;
    const [res, driRes] = await Promise.all([
      api.post('/api/body/analyze', { meal_plan: S.mealPlan || [], measurements: m }),
      fetch(`/api/body/dri?sex=${m.sex}&age=${m.age}&weight_kg=${m.weight_kg}&height_cm=${m.height_cm}&activity=${m.activity}`).then(r => r.json()),
    ]);

    if (!res.ok) { toast(res.error || 'Analysis failed', 'error'); return; }

    _lastNutrientData = res.nutrient_data;
    _lastNutrientMeta = res.nutrient_meta;
    _lastSupplements  = res.supplements;

    renderBodyStats(_bodyMeasurements);
    renderNutrientBars(res.nutrient_data, res.nutrient_meta);
    renderSupplements(res.supplements);
    if (driRes.ok) renderFullDRI(driRes, res.nutrient_data, res.supplements);
  } catch (e) {
    toast('Network error: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-flask"></i> Analyze My Nutrients'; }
  }
}

function renderBodyStats(m) {
  const card = document.getElementById('body-stats-card');
  const content = document.getElementById('body-stats-content');
  if (!card || !content) return;
  card.style.display = 'block';

  // BMI
  const heightM = m.height_cm / 100;
  const bmi = (m.weight_kg / (heightM * heightM)).toFixed(1);
  const bmiLabel = bmi < 18.5 ? 'Underweight' : bmi < 25 ? 'Healthy' : bmi < 30 ? 'Overweight' : 'Obese';
  const bmiColor = bmi < 18.5 ? '#f59e0b' : bmi < 25 ? '#059669' : bmi < 30 ? '#f97316' : '#ef4444';

  // TDEE (Mifflin-St Jeor)
  let bmr;
  if (m.sex === 'male') bmr = 10 * m.weight_kg + 6.25 * m.height_cm - 5 * m.age + 5;
  else                  bmr = 10 * m.weight_kg + 6.25 * m.height_cm - 5 * m.age - 161;
  const palMap = { sedentary: 1.2, light: 1.375, moderate: 1.55, active: 1.725, very_active: 1.9 };
  const tdee = Math.round(bmr * (palMap[m.activity] || 1.55));

  content.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      <div style="text-align:center;padding:8px;background:var(--bg);border-radius:6px">
        <div style="font-size:1.3rem;font-weight:700;color:${bmiColor}">${bmi}</div>
        <div style="font-size:.7rem;color:var(--text-light)">BMI · ${bmiLabel}</div>
      </div>
      <div style="text-align:center;padding:8px;background:var(--bg);border-radius:6px">
        <div style="font-size:1.3rem;font-weight:700;color:var(--primary)">${tdee}</div>
        <div style="font-size:.7rem;color:var(--text-light)">kcal/day (TDEE)</div>
      </div>
    </div>
  `;
}

function renderNutrientBars(data, meta) {
  const el = document.getElementById('body-nutrients-content');
  if (!el) return;
  if (!data || !data.coverage_pct) {
    el.innerHTML = '<p class="text-sm text-muted">No meal plan data — generate a meal plan first then re-analyze.</p>';
    return;
  }
  const coverage = data.coverage_pct;
  const intake   = data.daily_intake;
  const dri      = data.dri;
  const rows = (meta || []).map(m => {
    const pct  = Math.min(coverage[m.key] || 0, 100);
    const val  = (intake[m.key] || 0).toFixed(1);
    const req  = (dri[m.key]    || 0);
    const fill = pct >= 90 ? '#059669' : pct >= 60 ? '#f59e0b' : '#ef4444';
    return `
      <div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:3px">
          <span style="font-weight:500">${m.label}</span>
          <span style="color:var(--text-light)">${val} / ${req} ${m.unit} · <strong style="color:${fill}">${pct.toFixed(0)}%</strong></span>
        </div>
        <div style="height:7px;background:var(--bg);border-radius:9999px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:${fill};border-radius:9999px;transition:width .5s"></div>
        </div>
      </div>`;
  });
  const matched = (data.matched_foods || []).join(', ');
  el.innerHTML = rows.join('') +
    (matched ? `<p class="text-sm text-muted" style="margin-top:8px">Ingredients matched: ${matched}</p>` : '');
}

function renderSupplements(supps) {
  const card = document.getElementById('body-supps-card');
  const el   = document.getElementById('body-supps-content');
  if (!card || !el) return;
  card.style.display = 'block';
  if (!supps || !supps.length) {
    el.innerHTML = '<p class="text-sm text-muted">Your meal plan covers all key nutrients well — no critical supplements needed.</p>';
    return;
  }
  const priorityColor = { high: '#ef4444', medium: '#f59e0b', low: '#059669' };
  el.innerHTML = supps.map(s => `
    <div style="display:flex;align-items:flex-start;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)">
      <div style="flex-shrink:0;margin-top:2px">
        <span style="font-size:.65rem;font-weight:700;padding:2px 7px;border-radius:9999px;background:${priorityColor[s.priority]||'#64748b'}20;color:${priorityColor[s.priority]||'#64748b'};border:1px solid ${priorityColor[s.priority]||'#64748b'}40;white-space:nowrap">${s.priority?.toUpperCase()}</span>
      </div>
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <strong style="font-size:.85rem">${s.name}</strong>
          <span class="text-muted" style="font-size:.75rem">${s.dose}</span>
          ${s.blueprint ? '<span style="font-size:.65rem;padding:1px 5px;border-radius:4px;background:#6366f120;color:#6366f1;font-weight:600">Blueprint</span>' : ''}
          ${s.gap_pct != null ? `<span class="text-muted" style="font-size:.7rem">${s.gap_pct}% below DRI</span>` : ''}
        </div>
        <p style="font-size:.75rem;color:var(--text-light);margin:3px 0 0;line-height:1.4">${s.rationale || ''}</p>
        ${s.amazon_url ? `
        <a href="${s.amazon_url}" target="_blank" rel="noopener"
           style="display:inline-flex;align-items:center;gap:4px;margin-top:6px;font-size:.72rem;font-weight:600;
                  color:#ff9900;text-decoration:none;border:1px solid #ff990040;border-radius:9999px;
                  padding:2px 10px;background:#ff990010;transition:background .15s"
           onmouseover="this.style.background='#ff990025'" onmouseout="this.style.background='#ff990010'">
          <i class="fa-brands fa-amazon"></i> Buy on Amazon
        </a>` : ''}
      </div>
    </div>
  `).join('');
}

// ── LLM estimation of missing nutrients ───────────────────────────────────────
async function estimateMissingNutrients() {
  if (!S.mealPlan || !S.mealPlan.length) {
    toast('Generate a meal plan first so the AI has ingredients to analyse', 'error');
    return;
  }
  if (!S.settings.groqKey) {
    toast('Enter your Groq API key in Settings first', 'error');
    return;
  }
  const btn = document.getElementById('btn-estimate-nutrients');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Estimating…'; }

  try {
    const res = await api.post('/api/body/estimate-nutrients', {
      meal_plan: S.mealPlan,
      api_key:   S.settings.groqKey,
    });
    if (res.ok && res.estimates) {
      _extendedNutrients = res.estimates;
      // Show disclaimer note
      const note = document.getElementById('dri-estimate-note');
      if (note) note.style.display = 'inline';
      // Re-render the DRI table with estimated values injected
      const card = document.getElementById('body-dri-card');
      if (card && card.style.display !== 'none') {
        // Get the current DRI data by re-fetching (it's fast, no LLM)
        const m = {
          sex:       document.getElementById('body-sex')?.value      || 'male',
          age:       +document.getElementById('body-age')?.value     || 30,
          weight_kg: +document.getElementById('body-weight')?.value  || 75,
          height_cm: +document.getElementById('body-height')?.value  || 175,
          activity:  document.getElementById('body-activity')?.value || 'moderate',
        };
        const driRes = await fetch(
          `/api/body/dri?sex=${m.sex}&age=${m.age}&weight_kg=${m.weight_kg}&height_cm=${m.height_cm}&activity=${m.activity}`
        ).then(r => r.json());
        if (driRes.ok) renderFullDRI(driRes, _lastNutrientData, _lastSupplements);
      }
      const count = Object.keys(res.estimates).length;
      toast(`✅ ${count} nutrient values filled — USDA lab data where matched, AI estimate (~) for the rest`, 'success');
    } else {
      toast(res.error || 'Estimation failed', 'error');
    }
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Estimate missing with AI'; }
  }
}

// ── Body Coach (+ Nutrition Specialist sub-tab) ───────────────────────────────

let _activeCoachTab = 'body';   // 'body' | 'nutrition'

function _switchCoachTab(tab) {
  _activeCoachTab = tab;
  const isBody = tab === 'body';

  // Tab button styles
  const bodyBtn  = document.getElementById('coach-tab-body');
  const nutrBtn  = document.getElementById('coach-tab-nutrition');
  if (bodyBtn) {
    bodyBtn.style.background   = isBody ? 'var(--primary)' : 'transparent';
    bodyBtn.style.color        = isBody ? '#fff' : 'var(--text-light)';
    bodyBtn.style.borderColor  = isBody ? 'var(--primary)' : 'var(--border)';
  }
  if (nutrBtn) {
    nutrBtn.style.background   = !isBody ? '#10b981' : 'transparent';
    nutrBtn.style.color        = !isBody ? '#fff' : 'var(--text-light)';
    nutrBtn.style.borderColor  = !isBody ? '#10b981' : 'var(--border)';
  }

  // Descriptions
  const descBody = document.getElementById('coach-desc-body');
  const descNutr = document.getElementById('coach-desc-nutrition');
  if (descBody) descBody.style.display = isBody ? '' : 'none';
  if (descNutr) descNutr.style.display = isBody ? 'none' : '';

  // Input placeholder
  const input = document.getElementById('body-coach-input');
  if (input) {
    input.placeholder = isBody
      ? 'e.g. Why am I low on Vitamin D? What supplement should I take?'
      : 'e.g. I\'m 80kg, 180cm, want to lose weight — give me a keto meal plan';
  }

  // Re-render messages for the active tab
  _renderCoachMessages();
}

function _renderCoachMessages() {
  const el = document.getElementById('body-coach-messages');
  if (!el) return;
  const history = _activeCoachTab === 'body' ? _bodyCoachHistory : _nutritionChat;
  if (!history.length) {
    const placeholder = _activeCoachTab === 'body'
      ? 'Run "Analyze My Nutrients" first, then ask about your gaps, supplements, or meal improvements.'
      : 'Ask about macros, diet programs (keto, Mediterranean, IF), weekly meal plans, or food nutrition facts.';
    el.innerHTML = `
      <div class="text-sm text-muted" style="text-align:center;padding:24px 0;color:var(--text-light)">
        <i class="fa-solid fa-robot" style="font-size:1.8rem;display:block;margin-bottom:8px;color:var(--border)"></i>
        ${placeholder}
      </div>`;
    return;
  }
  // Render history bubbles
  el.innerHTML = '';
  history.forEach(m => {
    const bubble = document.createElement('div');
    const isUser = m.role === 'user';
    bubble.style.cssText = [
      'max-width:85%', 'padding:10px 14px', 'border-radius:12px',
      'font-size:.82rem', 'line-height:1.5', 'white-space:pre-wrap',
      isUser ? 'align-self:flex-end;background:var(--primary);color:#fff;border-bottom-right-radius:3px'
             : 'align-self:flex-start;background:var(--surface-alt,#f1f5f9);color:var(--text);border-bottom-left-radius:3px',
    ].join(';');
    const html = (m.content || '').replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">$1</a>');
    bubble.innerHTML = html;
    el.appendChild(bubble);
  });
  el.scrollTop = el.scrollHeight;
}

function _bodyCoachClear() {
  if (_activeCoachTab === 'body') {
    _bodyCoachHistory = [];
  } else {
    _nutritionChat = [];
  }
  _renderCoachMessages();
}

function _appendCoachBubble(role, text, actions) {
  const el = document.getElementById('body-coach-messages');
  if (!el) return;
  // Remove the placeholder if present
  const placeholder = el.querySelector('.text-muted');
  if (placeholder && !_bodyCoachHistory.length) placeholder.remove();

  const bubble = document.createElement('div');
  const isUser = role === 'user';
  bubble.style.cssText = [
    'max-width:85%', 'padding:10px 14px', 'border-radius:12px',
    'font-size:.82rem', 'line-height:1.5', 'white-space:pre-wrap',
    isUser ? 'align-self:flex-end;background:var(--primary);color:#fff;border-bottom-right-radius:3px'
           : 'align-self:flex-start;background:var(--surface-alt,#f1f5f9);color:var(--text);border-bottom-left-radius:3px',
  ].join(';');

  // Render markdown-like links: [text](url)
  const html = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">$1</a>');
  bubble.innerHTML = html;

  // Render action buttons for assistant messages
  if (!isUser && actions && actions.length) {
    const wrap = document.createElement('div');
    wrap.className = 'debate-actions';
    actions.forEach(act => {
      const btn = document.createElement('button');
      if (act.type === 'amazon') {
        btn.className = 'debate-action-btn btn-amazon';
        btn.innerHTML = `<i class="fa-brands fa-amazon"></i> ${act.label || 'Buy on Amazon'}`;
        btn.onclick = () => window.open(act.url, '_blank', 'noopener');
      } else if (act.type === 'add') {
        btn.className = 'debate-action-btn btn-add';
        btn.innerHTML = `<i class="fa-solid fa-basket-shopping"></i> ${act.label || 'Add to basket'}`;
        btn.onclick = () => _executeDebateAction(act, btn);
      } else if (act.type === 'replace') {
        btn.className = 'debate-action-btn btn-replace';
        btn.innerHTML = `<i class="fa-solid fa-arrows-rotate"></i> ${act.label || 'Replace'}`;
        btn.onclick = () => _executeDebateAction(act, btn);
      }
      wrap.appendChild(btn);
    });
    bubble.appendChild(wrap);
  }

  el.appendChild(bubble);
  el.scrollTop = el.scrollHeight;
}

async function sendBodyCoachMessage() {
  const input = document.getElementById('body-coach-input');
  const msg   = input?.value?.trim();
  if (!msg) return;

  if (!S.settings.groqKey) {
    toast('Enter your Groq API key in Settings to use the Coach', 'error');
    return;
  }

  const isBodyTab = _activeCoachTab === 'body';
  const history   = isBodyTab ? _bodyCoachHistory : _nutritionChat;

  // Push user message and re-render
  history.push({ role: 'user', content: msg });
  if (input) input.value = '';
  _renderCoachMessages();

  const btn = document.getElementById('btn-body-coach-send');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }

  // Thinking bubble
  const msgEl = document.getElementById('body-coach-messages');
  const thinking = document.createElement('div');
  thinking.style.cssText = 'align-self:flex-start;font-size:.78rem;color:var(--text-light);padding:6px 12px;font-style:italic';
  thinking.textContent = 'Thinking…';
  if (msgEl) { msgEl.appendChild(thinking); msgEl.scrollTop = msgEl.scrollHeight; }

  try {
    let res;
    if (isBodyTab) {
      // Body Coach — context-injected with real nutrient/supplement data
      res = await api.post('/api/body/coach-chat', {
        message:       msg,
        history:       history.slice(-20, -1),   // exclude the message we just pushed
        profile:       _bodyMeasurements,
        nutrient_data: _lastNutrientData || {},
        supplements:   _lastSupplements  || [],
        api_key:       S.settings.groqKey,
      });
    } else {
      // Nutrition Specialist — full LangGraph agent with macro/meal-plan tools
      res = await api.post('/api/nutrition-chat', {
        message: msg,
        history: history.slice(-20, -1),
        api_key: S.settings.groqKey,
      });
      // Normalise response shape (nutrition-chat returns {reply, nutrition_plan})
      if (res.ok && res.nutrition_plan?.length) {
        res.reply = (res.reply || '') + `\n\n📋 Weekly plan generated (${res.nutrition_plan.length} days).`;
      }
    }

    if (thinking.parentNode) thinking.remove();

    if (!res.ok) {
      history.push({ role: 'assistant', content: `Error: ${res.error || 'Unavailable'}` });
      _renderCoachMessages();
      return;
    }

    const rawReply = res.reply || '';
    if (isBodyTab) {
      // Body Coach can emit ---ACTIONS--- blocks
      const { displayText, actions } = _parseDebateActions(rawReply);
      history.push({ role: 'assistant', content: rawReply });
      _renderCoachMessages();
      // Append action buttons to the last assistant bubble
      if (actions.length) {
        const bubbles = msgEl?.querySelectorAll('div[style*="align-self:flex-start"]');
        if (bubbles?.length) _renderDebateActions(actions, bubbles[bubbles.length - 1]);
      }
    } else {
      history.push({ role: 'assistant', content: rawReply });
      _renderCoachMessages();
    }

  } catch (e) {
    if (thinking.parentNode) thinking.remove();
    history.push({ role: 'assistant', content: `Network error: ${e.message}` });
    _renderCoachMessages();
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send'; }
  }
}

function renderFullDRI(d, nutrientData, supplements) {
  const card = document.getElementById('body-dri-card');
  const el   = document.getElementById('body-dri-content');
  if (!card || !el || !d) return;
  card.style.display = 'block';

  const n  = d.nutrients || {};
  const dt = d.dri_type  || {};

  // ── Build "current level" map (DRI key → value in DRI units) ────────────────
  const curLvl  = {};   // no supplements
  const suppLvl = {};   // after recommended supplements

  // Macros from meal plan
  if (S.mealPlan && S.mealPlan.length) {
    const days = [...new Set(S.mealPlan.map(m => m.Day))].length || 1;
    const tot  = S.mealPlan.reduce((a, m) => {
      a.cal  += +(m.calories || 0);
      a.prot += +(m.protein  || 0);
      a.carb += +(m.carbs    || 0);
      a.fat  += +(m.fat      || 0);
      return a;
    }, { cal: 0, prot: 0, carb: 0, fat: 0 });
    curLvl._calories = Math.round(tot.cal  / days);
    curLvl._protein  = +(tot.prot / days).toFixed(1);
    curLvl._carbs    = Math.round(tot.carb / days);
    curLvl._fat      = Math.round(tot.fat  / days);
  }

  // Micronutrients from meal plan analysis (tracked by food CSV)
  if (nutrientData && nutrientData.daily_intake) {
    for (const [metaKey, { driKey, conv }] of Object.entries(_NUTRIENT_TO_DRI)) {
      const val = nutrientData.daily_intake[metaKey];
      if (val != null) curLvl[driKey] = conv(val);
    }
  }

  // LLM-estimated nutrients (filled in when user clicks "Estimate with AI")
  // Key mapping: LLM key → DRI table key
  const _EXT_MAP = {
    vit_a_mcg_rae: 'vit_a_mcg',
    vit_b1_mg:     'vit_b1_mg',
    vit_b2_mg:     'vit_b2_mg',
    vit_b3_mg_ne:  'vit_b3_mg',
    vit_b5_mg:     'vit_b5_mg',
    vit_b6_mg:     'vit_b6_mg',
    vit_b7_mcg:    'vit_b7_mcg',
    vit_e_mg:      'vit_e_mg',
    choline_mg:    'choline_mg',
    copper_mcg:    'copper_mcg',
    iodine_mcg:    'iodine_mcg',
    manganese_mg:  'manganese_mg',
    phosphorus_mg: 'phosphorus_mg',
  };
  const estimatedKeys = new Set();  // tracks which DRI keys come from LLM
  if (_extendedNutrients) {
    for (const [extKey, driKey] of Object.entries(_EXT_MAP)) {
      const val = _extendedNutrients[extKey];
      if (val != null && curLvl[driKey] == null) {  // only fill gaps (don't overwrite measured)
        curLvl[driKey] = +val.toFixed(1);
        estimatedKeys.add(driKey);
      }
    }
  }

  // Copy current into after-supp baseline, then add supplement doses
  Object.assign(suppLvl, curLvl);
  if (supplements && supplements.length) {
    for (const s of supplements) {
      const mk = s.nutrient_key;
      if (!mk || !_NUTRIENT_TO_DRI[mk]) continue;
      const { driKey, conv } = _NUTRIENT_TO_DRI[mk];
      const doseRaw = _parseDose(s.dose);
      if (doseRaw == null) continue;
      const doseConverted = conv(doseRaw);
      suppLvl[driKey] = +((suppLvl[driKey] || 0) + doseConverted).toFixed(1);
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────
  const badge = (type) => {
    const isRDA = type === 'RDA';
    const clr   = { RDA:'#059669', AI:'#b45309', Calc:'#6366f1', 'RDA×':'#059669', AMDR:'#3b82f6' };
    const c = clr[type] || '#64748b';
    return `<span style="font-size:.6rem;padding:1px 5px;border-radius:4px;background:${c}18;color:${c};font-weight:700;white-space:nowrap">${type||'—'}</span>`;
  };

  const pctColor = (pct) =>
    pct == null ? '#94a3b8' : pct >= 90 ? '#059669' : pct >= 50 ? '#f59e0b' : '#ef4444';

  const levelCell = (val, target, isEst) => {
    if (val == null) return `<span style="color:#cbd5e1;font-size:.75rem">—</span>`;
    const pct = target ? Math.min(val / target * 100, 999) : null;
    const c   = pctColor(pct);
    const pctTxt = pct != null ? `<span style="font-size:.62rem;color:${c};margin-left:3px">${pct < 10 ? pct.toFixed(1) : Math.round(pct)}%</span>` : '';
    const estMark = isEst ? `<span style="font-size:.58rem;color:#f59e0b;margin-left:2px" title="AI estimate">~</span>` : '';
    return `<span style="font-weight:600;color:${c};font-size:.78rem">${val < 10 ? val.toFixed(1) : Math.round(val)}</span>${pctTxt}${estMark}`;
  };

  const row = (name, target, unit, type, curKey, even, suppKey) => {
    const cur    = curKey  != null ? curLvl[curKey]  : undefined;
    const aft    = suppKey != null ? suppLvl[suppKey] : cur;
    const isEst  = curKey != null && estimatedKeys.has(curKey);
    return `<tr style="background:${even?'var(--bg)':'transparent'}">
      <td style="padding:5px 8px;font-weight:500;color:var(--text);font-size:.78rem">${name}</td>
      <td style="padding:5px 8px;text-align:right;font-weight:700;color:var(--primary);font-size:.8rem">${target ?? '—'}</td>
      <td style="padding:5px 8px">${levelCell(cur, target, isEst)}</td>
      <td style="padding:5px 8px">${levelCell(aft, target, isEst)}</td>
      <td style="padding:5px 8px;color:var(--text-light);font-size:.72rem;white-space:nowrap">${unit}</td>
      <td style="padding:5px 8px;text-align:center">${badge(type)}</td>
    </tr>`;
  };

  const thead = `<thead><tr style="border-bottom:1px solid var(--border)">
    <th style="padding:4px 8px;text-align:left;font-size:.68rem;color:var(--text-muted);font-weight:600">Nutrient</th>
    <th style="padding:4px 8px;text-align:right;font-size:.68rem;color:var(--text-muted);font-weight:600">Target</th>
    <th style="padding:4px 8px;font-size:.68rem;color:var(--text-muted);font-weight:600">No Supp</th>
    <th style="padding:4px 8px;font-size:.68rem;color:var(--text-muted);font-weight:600">+ Supp</th>
    <th style="padding:4px 8px;font-size:.68rem;color:var(--text-muted);font-weight:600">Unit</th>
    <th style="padding:4px 8px;text-align:center;font-size:.68rem;color:var(--text-muted);font-weight:600">Type</th>
  </tr></thead>`;

  const table = (rows) =>
    `<table style="width:100%;border-collapse:collapse">${thead}<tbody>${rows.join('')}</tbody></table>`;

  const section = (title, rows) =>
    `<div style="margin-bottom:16px">
       <div style="font-size:.77rem;font-weight:700;color:var(--primary);padding:5px 8px;background:var(--primary-xlight);border-radius:6px;margin-bottom:6px">${title}</div>
       ${table(rows)}
     </div>`;

  // ── Row definitions ──────────────────────────────────────────────────────────
  const macroRows = [
    row('Calories (TDEE)',  d.tdee,      'kcal/day', 'Calc',  '_calories', true),
    row('Protein',          d.protein_g, 'g/day',    'RDA×',  '_protein',  false),
    row('Carbohydrates',    d.carbs_g,   'g/day',    'AMDR',  '_carbs',    true),
    row('Fat',              d.fat_g,     'g/day',    'AMDR',  '_fat',      false),
    row('Dietary Fiber',    n.fiber_g,   'g/day',    dt.fiber_g, null,     true),
    row('Water',            n.water_l,   'L/day',    dt.water_l, null,     false),
  ];

  const vitaminRows = [
    // [name, DRI target, unit, type, driKey (for curLvl/suppLvl lookup)]
    // driKey = null → no food CSV data; with "Estimate AI" button the LLM fills these in
    ['Vitamin A',                    n.vit_a_mcg,   'mcg RAE', dt.vit_a_mcg,   'vit_a_mcg'],
    ['Vitamin B1 (Thiamin)',          n.vit_b1_mg,   'mg',      dt.vit_b1_mg,   'vit_b1_mg'],
    ['Vitamin B2 (Riboflavin)',       n.vit_b2_mg,   'mg',      dt.vit_b2_mg,   'vit_b2_mg'],
    ['Vitamin B3 (Niacin)',           n.vit_b3_mg,   'mg NE',   dt.vit_b3_mg,   'vit_b3_mg'],
    ['Vitamin B5 (Pantothenic Acid)', n.vit_b5_mg,   'mg',      dt.vit_b5_mg,   'vit_b5_mg'],
    ['Vitamin B6',                    n.vit_b6_mg,   'mg',      dt.vit_b6_mg,   'vit_b6_mg'],
    ['Vitamin B7 (Biotin)',           n.vit_b7_mcg,  'mcg',     dt.vit_b7_mcg,  'vit_b7_mcg'],
    ['Vitamin B9 (Folate)',           n.vit_b9_mcg,  'mcg DFE', dt.vit_b9_mcg,  'vit_b9_mcg'],
    ['Vitamin B12',                   n.vit_b12_mcg, 'mcg',     dt.vit_b12_mcg, 'vit_b12_mcg'],
    ['Vitamin C',                     n.vit_c_mg,    'mg',      dt.vit_c_mg,    'vit_c_mg'],
    ['Vitamin D',                     n.vit_d_mcg,   'mcg',     dt.vit_d_mcg,   'vit_d_mcg'],
    ['Vitamin E',                     n.vit_e_mg,    'mg',      dt.vit_e_mg,    'vit_e_mg'],
    ['Vitamin K',                     n.vit_k_mcg,   'mcg',     dt.vit_k_mcg,   'vit_k_mcg'],
    ['Choline',                       n.choline_mg,  'mg',      dt.choline_mg,  'choline_mg'],
  ].map(([name, target, unit, type, driKey], i) =>
    row(name, target, unit, type, driKey, i % 2 === 0, driKey));

  const mineralRows = [
    ['Calcium',    n.calcium_mg,     'mg',  dt.calcium_mg,    'calcium_mg'],
    ['Chromium',   n.chromium_mcg,   'mcg', dt.chromium_mcg,  null],          // unmeasurable from ingredients
    ['Copper',     n.copper_mcg,     'mcg', dt.copper_mcg,    'copper_mcg'],
    ['Fluoride',   n.fluoride_mg,    'mg',  dt.fluoride_mg,   null],           // water-dependent, skip
    ['Iodine',     n.iodine_mcg,     'mcg', dt.iodine_mcg,    'iodine_mcg'],
    ['Iron',       n.iron_mg,        'mg',  dt.iron_mg,       'iron_mg'],
    ['Magnesium',  n.magnesium_mg,   'mg',  dt.magnesium_mg,  'magnesium_mg'],
    ['Manganese',  n.manganese_mg,   'mg',  dt.manganese_mg,  'manganese_mg'],
    ['Molybdenum', n.molybdenum_mcg, 'mcg', dt.molybdenum_mcg,null],          // unmeasurable from ingredients
    ['Phosphorus', n.phosphorus_mg,  'mg',  dt.phosphorus_mg, 'phosphorus_mg'],
    ['Potassium',  n.potassium_mg,   'mg',  dt.potassium_mg,  'potassium_mg'],
    ['Selenium',   n.selenium_mcg,   'mcg', dt.selenium_mcg,  'selenium_mcg'],
    ['Sodium',     n.sodium_mg,      'mg',  dt.sodium_mg,     null],
    ['Zinc',       n.zinc_mg,        'mg',  dt.zinc_mg,       'zinc_mg'],
  ].map(([name, target, unit, type, driKey], i) =>
    row(name, target, unit, type, driKey, i % 2 === 0, driKey));

  el.innerHTML =
    section('🍞 Macronutrients', macroRows) +
    section('🌟 Vitamins', vitaminRows) +
    section('⚗️ Minerals', mineralRows) +
    `<div style="margin-top:12px;padding:8px 10px;border-radius:6px;background:var(--bg);display:flex;gap:16px;flex-wrap:wrap;font-size:.68rem;color:var(--text-muted)">
       <span>🟢 ≥90% of target</span><span>🟡 50–89%</span><span>🔴 &lt;50%</span>
       <span style="color:#94a3b8">— = not tracked in meal plan</span>
     </div>
     <p style="font-size:.67rem;color:var(--text-muted);margin-top:8px;padding-top:8px;border-top:1px solid var(--border);text-align:center;line-height:1.6">
       📚 Based on USDA Dietary Reference Intakes (DRIs), National Academies of Sciences, Engineering, and Medicine.<br>
       RDA = Recommended Dietary Allowance &nbsp;|&nbsp; AI = Adequate Intake &nbsp;|&nbsp;
       Calc = Mifflin–St Jeor × PAL &nbsp;|&nbsp; AMDR = Acceptable Macronutrient Distribution Range
     </p>`;
}

async function checkRagStatus() {
  const statusEl = document.getElementById('news-rag-status');
  if (!statusEl) return;
  try {
    const res = await fetch('/api/body/news/status').then(r => r.json());
    if (res.ready) {
      const trendsLabel = res.trends_count ? ` · ${res.trends_count} trends detected` : '';
      statusEl.textContent = `Vector index ready — ${res.chunks} chunks · ${res.kv_cache_size || 0} articles in KV cache${trendsLabel}`;
      statusEl.style.color = '#059669';
      loadNewsTrends();
    } else {
      statusEl.textContent = 'Vector index loading… (ingestion runs 60 s after server start)';
      statusEl.style.color = '#f59e0b';
      setTimeout(checkRagStatus, 15000);
    }
  } catch (e) {
    statusEl.textContent = 'Could not reach news index';
  }
}

async function loadNewsTrends() {
  const strip = document.getElementById('news-trends-strip');
  if (!strip) return;
  try {
    const res = await fetch('/api/body/news/trends').then(r => r.json());
    const trends = res.trends || [];
    if (!trends.length) return;
    const colors = { Emergence: '#059669', Acceleration: '#3b82f6', Disruption: '#ef4444' };
    const icons  = { Emergence: 'fa-seedling', Acceleration: 'fa-rocket', Disruption: 'fa-bolt' };
    strip.style.display = 'block';
    strip.innerHTML = `
      <div style="font-size:.65rem;font-weight:700;color:var(--text-light);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em">
        <i class="fa-solid fa-chart-line" style="margin-right:4px"></i>Trend Signals
      </div>
      ${trends.map(t => `
        <div style="display:flex;gap:6px;align-items:flex-start;margin-bottom:6px;cursor:pointer"
             title="${t.summary || ''}" onclick="this.querySelector('.trend-summary').classList.toggle('hidden')">
          <span style="flex-shrink:0;background:${colors[t.type]||'#6366f1'}20;color:${colors[t.type]||'#6366f1'};
                       border-radius:4px;padding:2px 6px;font-size:.6rem;font-weight:700;white-space:nowrap">
            <i class="fa-solid ${icons[t.type]||'fa-circle'}" style="margin-right:3px"></i>${t.type}
          </span>
          <div style="font-size:.72rem;line-height:1.3">
            <div style="font-weight:600">${t.topic}</div>
            <div class="trend-summary hidden text-muted" style="font-size:.67rem;margin-top:2px">${t.summary||''}</div>
          </div>
        </div>`).join('')}
    `;
  } catch (e) { /* trends are optional — fail silently */ }
}

async function queryNews() {
  const input  = document.getElementById('news-query-input');
  const question = input?.value?.trim();
  if (!question) return;
  if (!S.settings.groqKey) { toast('Set your Groq API key in Settings first', 'error'); return; }

  const btn       = document.getElementById('btn-news-query');
  const answerBox = document.getElementById('news-query-answer');
  const answerEl  = document.getElementById('news-answer-text');
  const sourcesEl = document.getElementById('news-answer-sources');

  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; }
  if (answerBox) answerBox.style.display = 'block';
  if (answerEl)  answerEl.textContent = 'Searching the research…';
  if (sourcesEl) sourcesEl.innerHTML = '';

  try {
    const res = await api.post('/api/body/news/query', {
      question,
      api_key: S.settings.groqKey,
    });

    if (res.ok) {
      if (answerEl) answerEl.textContent = res.answer || '(no answer)';
      if (sourcesEl) {
        const criticBadge = res.critic_score != null
          ? `<span style="float:right;font-size:.65rem;background:#f0fdf4;color:#059669;border-radius:4px;padding:1px 6px" title="Writer-Critic quality score">✓ ${res.critic_score.toFixed(1)}/10${res.iterations > 1 ? ` (${res.iterations} drafts)` : ''}</span>`
          : '';
        sourcesEl.innerHTML = `<div style="font-size:.68rem;font-weight:600;color:var(--text-light);margin-bottom:4px">Sources ${criticBadge}</div>` +
          (res.sources?.length ? res.sources.map(s => `
            <div style="font-size:.7rem;margin-bottom:3px">
              ${s.url ? `<a href="${s.url}" target="_blank" style="color:var(--primary)">${s.title || s.source}</a>` : `<span>${s.title || s.source}</span>`}
              <span class="text-muted" style="margin-left:4px">[${s.source}]</span>
            </div>`).join('') : '');
      }
    } else {
      if (answerEl) answerEl.textContent = `Error: ${res.error || 'Query failed'}`;
    }
  } catch (e) {
    if (answerEl) answerEl.textContent = `Network error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Ask'; }
  }
}

// ── Chat ─────────────────────────────────────────────────────────────────────
function toggleChat() {
  const panel = document.getElementById('chat-panel');
  const isHidden = panel.classList.contains('hidden');
  panel.classList.toggle('hidden');
  document.body.classList.toggle('chat-open', isHidden);
  if (isHidden) {
    document.getElementById('chat-input')?.focus();
    renderChatMessages();
  }
}

function renderChatMessages() {
  const c = document.getElementById('chat-messages');
  if (!c) return;
  if (!S.chat.length) {
    c.innerHTML = `<div class="text-center text-muted text-sm" style="padding:40px 10px">
      <i class="fa-solid fa-robot" style="font-size:2rem;display:block;margin-bottom:10px;color:var(--border)"></i>
      Hi! I'm your grocery assistant. Ask me about recipes, products, or nutrition.</div>`;
    return;
  }
  c.innerHTML = S.chat.map(m => {
    let content = m.content.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
    let extra = '';
    if (m.basket_items?.length) {
      extra = `<div class="basket-offer"><strong>${m.basket_items.length} item(s) to add:</strong><br>` +
        m.basket_items.map(b => `${b.name} — &euro;${(b.price||0).toFixed(2)}`).join('<br>') +
        `<br><button class="btn-primary btn-sm mt-1" onclick='chatAddToBasket(${JSON.stringify(m.basket_items).replace(/'/g,"&#39;")})'>Add to Basket</button></div>`;
    }
    return `<div class="chat-msg ${m.role}">${content}${extra}</div>`;
  }).join('');
  c.scrollTop = c.scrollHeight;
}

function chatAddToBasket(items) {
  items.forEach(it => addToBasket(it));
}

async function sendChatMessage() {
  const input = document.getElementById('chat-input');
  const msg = input?.value?.trim();
  if (!msg) return;
  if (!S.settings.groqKey) {
    toast('Set your Groq API key in Settings', 'error'); return;
  }

  S.chat.push({ role: 'user', content: msg });
  input.value = '';
  renderChatMessages();

  // Build history for API (last 20 messages)
  const history = S.chat.slice(-20).map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content }));

  try {
    const res = await api.post('/api/chat', {
      message: msg,
      history: history.slice(0, -1), // exclude the current message
      api_key: S.settings.groqKey || '',
    });
    if (res.ok) {
      const entry = { role: 'assistant', content: res.reply || 'No response' };
      if (res.basket_items?.length) entry.basket_items = res.basket_items;
      S.chat.push(entry);
    } else {
      S.chat.push({ role: 'assistant', content: `Error: ${res.error || 'Unknown error'}` });
    }
  } catch (e) {
    S.chat.push({ role: 'assistant', content: `Network error: ${e.message}` });
  }
  save('chatMessages');
  renderChatMessages();
}

// ── Settings ─────────────────────────────────────────────────────────────────
function openSettings() {
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('setting-groq-key').value = S.settings.groqKey || '';
  // Show server key pool status
  const statusEl = document.getElementById('server-key-status');
  if (statusEl) {
    const avail = S._serverKeysAvailable || 0;
    const total = S._serverKeysTotal || 0;
    if (total > 0) {
      const color = avail > 0 ? '#10b981' : '#f43f5e';
      statusEl.innerHTML = `<i class="fa-solid fa-server" style="color:${color}"></i> Server key pool: <strong style="color:${color}">${avail}/${total} available</strong> — your own key above takes priority if set.`;
    } else {
      statusEl.innerHTML = `<i class="fa-solid fa-circle-info"></i> No server keys configured — enter your own key above.`;
    }
  }
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

function saveSettings() {
  S.settings.groqKey = document.getElementById('setting-groq-key').value.trim();
  save('settings');
  closeModal();
  toast('Settings saved', 'success');
}

// ── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  // Load config — also pre-fills the Groq key if set server-side via .env
  try {
    S.config = await api.get('/api/config');
    if (S.config.groq_key && !S.settings.groqKey) {
      S.settings.groqKey = S.config.groq_key;
      save('settings');
    }
    // Store server key availability for UI hints
    S._serverKeysAvailable = S.config.server_keys_available || 0;
    S._serverKeysTotal     = S.config.server_keys_total || 0;
  } catch (e) { /* use defaults */ }

  // Event listeners
  document.getElementById('btn-settings')?.addEventListener('click', openSettings);
  document.getElementById('btn-save-settings')?.addEventListener('click', saveSettings);
  document.getElementById('btn-chat-toggle')?.addEventListener('click', toggleChat);
  document.getElementById('btn-chat-open')?.addEventListener('click', toggleChat);
  document.getElementById('btn-chat-close')?.addEventListener('click', toggleChat);
  document.getElementById('btn-chat-send')?.addEventListener('click', sendChatMessage);
  document.getElementById('chat-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMessage(); });
  document.querySelectorAll('.modal-close').forEach(b => b.addEventListener('click', closeModal));
  document.getElementById('modal-overlay')?.addEventListener('click', e => { if (e.target.id === 'modal-overlay') closeModal(); });
  document.getElementById('btn-menu')?.addEventListener('click', () => document.getElementById('sidebar')?.classList.toggle('open'));

  updateBadge();
  window.addEventListener('hashchange', route);
  route();
}

document.addEventListener('DOMContentLoaded', init);
