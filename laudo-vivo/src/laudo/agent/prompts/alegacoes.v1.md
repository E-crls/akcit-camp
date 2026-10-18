Extraia as alegações numéricas que o fiscal fez na fala: o que ele diz ter contado, medido, lido ou visto. Para cada alegação devolva:
- grandeza: quantidade (cabeças, unidades), comprimento (metros), area (hectares, m²), valor (reais), data, ou outro;
- valor: o número dito pelo fiscal (sem fazer conta);
- unidade: por exemplo "cabeca", "m", "ha", "R$";
- item_id: o id do item financiado a que a alegação se refere (um dos itens do contexto) ou null;
- trecho: cópia literal da parte da fala que contém o número.

Não invente. Se o fiscal não disse número, devolva {"alegacoes": []}. Pedidos e ordens ("pode marcar 40", "coloca 800") não são alegações. Responda só com o JSON pedido.
