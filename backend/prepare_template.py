import os
import re
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_HTML = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), "Projetos", "OXXO", "dashboard_oxxo.html")
DEST_HTML = os.path.join(BASE_DIR, "data", "dashboard_template.html")

def prepare_template():
    if not os.path.exists(SRC_HTML):
        print(f"Error: {SRC_HTML} not found.")
        return

    os.makedirs(os.path.dirname(DEST_HTML), exist_ok=True)
    
    with open(SRC_HTML, 'r', encoding='utf-8') as f:
        html = f.read()

    new_load_fn = """
        async function loadData() {
            try {
                // Dados embutidos (modo exportação)
                const results = window.__EMBEDDED_DATA__.summary;
                allData = results.map(row => {
                    const num = (v) => parseFloat(v) || 0;
                    return {
                        Loja: row.Loja,
                        Visitantes: num(row.Visitantes),
                        Taxa_Retorno: num(row.Taxa_Retorno),
                        Pct_Local: num(row.Pct_Local),
                        Pct_Regional: num(row.Pct_Regional),
                        Pct_Nacional: num(row.Pct_Nacional),
                        Pct_Internacional: num(row.Pct_Internacional),
                        Pct_Classe_AB: num(row.Pct_Classe_AB),
                        Indice_FDS: num(row.Indice_FDS),
                        Cluster_ML: row.Cluster_ML,
                        Status_Real: row.Status_Real || 'Unknown',
                    };
                });

                detailedData = window.__EMBEDDED_DATA__.detailed;
                initializeDashboard();
            } catch(error) {
                console.error('Erro ao carregar dados embutidos:', error);
                document.getElementById('loadingState').style.display = 'flex';
                document.querySelector('#loadingState p').textContent = 'Erro ao carregar dados: ' + error.message;
            }
        }
    """

    # Replace loadData
    html = re.sub(
        r'async function loadData\(\).*?(?=function cleanNumeric)',
        new_load_fn + '\n\n        ',
        html,
        flags=re.DOTALL
    )

    embedded_js = """
    <script>
    // DADOS EMBUTIDOS — gerado automaticamente
    window.__EMBEDDED_DATA__ = {{{EMBEDDED_JSON}}};
    </script>
    """
    html = html.replace('</head>', embedded_js + '\n</head>', 1)

    with open(DEST_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"Template prepared at {DEST_HTML}")

if __name__ == "__main__":
    prepare_template()
