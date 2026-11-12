document.querySelectorAll("[data-lookup-url]").forEach((input) => {
  const form = input.closest("form");
  const target = document.getElementById(input.dataset.target);
  const results = document.getElementById(input.dataset.results);
  let timer;
  let requestId = 0;

  input.addEventListener("input", () => {
    target.value = "";
    input.setCustomValidity("");
    results.replaceChildren();
    const query = input.value.trim();
    if (query.length < 2) {
      results.textContent = "Type at least two characters to search.";
      return;
    }

    const activeRequest = ++requestId;
    results.textContent = "Searching...";
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const response = await fetch(
          `${input.dataset.lookupUrl}?q=${encodeURIComponent(query)}`,
        );
        if (!response.ok) {
          throw new Error(`Search request failed with HTTP ${response.status}`);
        }
        const data = await response.json();
        if (activeRequest !== requestId) {
          return;
        }
        results.replaceChildren();
        if (data.results.length === 0) {
          results.textContent = "No matching records.";
          return;
        }
        for (const result of data.results) {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "lookup-result";
          option.textContent = result.label;
          option.addEventListener("click", () => {
            target.value = result.id;
            input.value = result.label;
            results.replaceChildren();
          });
          results.append(option);
        }
      } catch (error) {
        if (activeRequest === requestId) {
          results.textContent = "Search failed. Please try again.";
          console.error(error);
        }
      }
    }, 250);
  });

  form.addEventListener("submit", (event) => {
    if (!target.value) {
      event.preventDefault();
      input.setCustomValidity("Choose a record from the search results.");
      input.reportValidity();
    }
  });
});
