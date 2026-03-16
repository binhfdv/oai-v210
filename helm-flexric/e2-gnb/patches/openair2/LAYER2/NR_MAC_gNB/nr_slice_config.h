#ifndef NR_SLICE_CONFIG_H
#define NR_SLICE_CONFIG_H

#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>

#define NR_MAX_SLICES 8

typedef struct {
  uint8_t  sst;
  uint32_t sd;
  uint16_t pos_low;   /* first RB index (inclusive, 0-based within BWP) */
  uint16_t pos_high;  /* last  RB index (inclusive) */
  bool     valid;
} nr_slice_entry_t;

typedef struct {
  pthread_mutex_t  lock;
  nr_slice_entry_t entries[NR_MAX_SLICES];
  int              num_entries;
} nr_slice_table_t;

extern nr_slice_table_t g_nr_slice_table;

void nr_slice_table_init(void);
void nr_slice_table_set(uint8_t sst, uint32_t sd, uint16_t pos_low, uint16_t pos_high);
bool nr_slice_table_lookup(uint8_t sst, uint32_t sd, uint16_t *pos_low, uint16_t *pos_high);

#endif /* NR_SLICE_CONFIG_H */
