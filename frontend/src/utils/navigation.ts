export function navigateTo(path: string) {
  // Comparar só o `pathname` fazia `/manage?area=X` → `/manage` ser ignorado,
  // porque o caminho é o mesmo e só a busca muda. Quem decide se já estamos no
  // destino é o endereço inteiro.
  if (window.location.pathname + window.location.search === path) return
  window.history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}
