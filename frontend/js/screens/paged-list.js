// The list box shared by Serviços, Profissionais and Acessos: one compact row per item, a search field
// once the list is long, and pages of PAGE_SIZE rows ("‹ 1 de 3 ›"). The search looks at every item,
// not just the page shown, and goes back to the first page.
//
// The pages are cut here, on the screen: the API answers whole lists on purpose, because the agenda and
// the forms need every service and professional at once (offline too), and the lists are small by design
// (at most 200 services and 50 professionals).
import { h, render } from "../util.js";

export const PAGE_SIZE = 10;
const SEARCH_FROM = 6;                          // a search field from this many items on

/** Lowercase, without accents: "Coloração" is found by "coloracao". */
const plain = (text) => text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** `items` with their `name`; `row(item)` draws one <li class="list-item">. `label`: what the list
 *  holds, for the search's placeholder ("serviços"). `searchText(item)`: what the search looks at
 *  (the name, unless told otherwise: clients are also found by phone). */
export function pagedList(items, row, { label, searchText = (item) => item.name }) {
  let page = 0, shown = items;
  const list = h("ul", { className: "item-list" });
  const nothingFound = h("p", { className: "muted list-empty", hidden: true }, "Nada encontrado.");
  const pager = h("div", { className: "pager", role: "navigation", "aria-label": "Páginas" });

  function draw() {
    const pages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
    page = Math.min(page, pages - 1);
    render(list, shown.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map(row));
    nothingFound.hidden = shown.length > 0;
    const first = page * PAGE_SIZE + 1, last = Math.min(shown.length, (page + 1) * PAGE_SIZE);
    render(pager, pages > 1 && [
      h("span", { className: "muted" }, `${first}–${last} de ${shown.length}`),
      h("button", { className: "secondary small", "aria-label": "Página anterior", disabled: page === 0,
        onclick: () => { page -= 1; draw(); list.scrollTop = 0; } }, "‹"),
      h("span", { className: "pager-page" }, `${page + 1} de ${pages}`),
      h("button", { className: "secondary small", "aria-label": "Próxima página", disabled: page === pages - 1,
        onclick: () => { page += 1; draw(); list.scrollTop = 0; } }, "›")]);
  }

  const search = items.length >= SEARCH_FROM && h("input", { type: "search", className: "list-search",
    placeholder: `Buscar ${label}`, "aria-label": `Buscar ${label}`,
    oninput: (e) => {
      const wanted = plain(e.target.value.trim());
      shown = wanted ? items.filter((item) => plain(searchText(item)).includes(wanted)) : items;
      page = 0;
      draw();
    } });
  draw();
  return h("div", { className: "card list-card" }, search, list, nothingFound, pager);
}
