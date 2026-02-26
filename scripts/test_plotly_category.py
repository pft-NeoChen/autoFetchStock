import pandas as pd
import plotly.graph_objects as go

df = pd.DataFrame({
    'date': ['2024-01-01', '2024-01-04', '2024-01-05'],
    'val': [1, 2, 3]
})

fig = go.Figure()
fig.add_trace(go.Scatter(x=df['date'], y=df['val']))
fig.update_xaxes(type="category", tickformat="%m/%d")

print(fig.to_json()[:500])
