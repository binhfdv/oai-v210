#include "nr_slice_config.h"
#include <string.h>
#include <stdio.h>

nr_slice_table_t g_nr_slice_table;

void nr_slice_table_init(void)
{
  pthread_mutex_init(&g_nr_slice_table.lock, NULL);
  memset(g_nr_slice_table.entries, 0, sizeof(g_nr_slice_table.entries));
  g_nr_slice_table.num_entries = 0;
}

void nr_slice_table_set(uint8_t sst, uint32_t sd, uint16_t pos_low, uint16_t pos_high)
{
  pthread_mutex_lock(&g_nr_slice_table.lock);

  /* Update existing entry */
  for (int i = 0; i < NR_MAX_SLICES; i++) {
    nr_slice_entry_t *e = &g_nr_slice_table.entries[i];
    if (e->valid && e->sst == sst && e->sd == sd) {
      e->pos_low  = pos_low;
      e->pos_high = pos_high;
      printf("[NR SLICE]: updated (sst=%u sd=%u) -> RBs [%u..%u]\n",
             sst, sd, pos_low, pos_high);
      fflush(stdout);
      pthread_mutex_unlock(&g_nr_slice_table.lock);
      return;
    }
  }

  /* Find a free slot */
  for (int i = 0; i < NR_MAX_SLICES; i++) {
    nr_slice_entry_t *e = &g_nr_slice_table.entries[i];
    if (!e->valid) {
      e->sst      = sst;
      e->sd       = sd;
      e->pos_low  = pos_low;
      e->pos_high = pos_high;
      e->valid    = true;
      if (i >= g_nr_slice_table.num_entries)
        g_nr_slice_table.num_entries = i + 1;
      printf("[NR SLICE]: added (sst=%u sd=%u) -> RBs [%u..%u]\n",
             sst, sd, pos_low, pos_high);
      fflush(stdout);
      pthread_mutex_unlock(&g_nr_slice_table.lock);
      return;
    }
  }

  printf("[NR SLICE]: WARNING - slice table full, cannot add (sst=%u sd=%u)\n", sst, sd);
  fflush(stdout);
  pthread_mutex_unlock(&g_nr_slice_table.lock);
}

bool nr_slice_table_lookup(uint8_t sst, uint32_t sd, uint16_t *pos_low, uint16_t *pos_high)
{
  pthread_mutex_lock(&g_nr_slice_table.lock);
  for (int i = 0; i < g_nr_slice_table.num_entries; i++) {
    const nr_slice_entry_t *e = &g_nr_slice_table.entries[i];
    if (e->valid && e->sst == sst && e->sd == sd) {
      *pos_low  = e->pos_low;
      *pos_high = e->pos_high;
      pthread_mutex_unlock(&g_nr_slice_table.lock);
      return true;
    }
  }
  pthread_mutex_unlock(&g_nr_slice_table.lock);
  return false;
}
