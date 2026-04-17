import { Component, OnInit, QueryList, ViewChild, ViewChildren } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet } from '@angular/router';
import { TrafficType } from './models/traffic_type.model';
import { AIModel } from './models/scenario.model';
import { NgxGaugeModule } from 'ngx-gauge';
import { WebsocketService } from './services/websocket-service';
import { environment } from '../environments/environment';
import { BackendService } from './services/backend_service';
import { Statistic } from './models/chart_data.mode';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, NgxGaugeModule,
  ],

  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnInit {

  trafficTypes: TrafficType[] = [
    {
      label: "Haptic",
      value: "haptic",
      icon: "bi bi-hand-index-thumb",
      pkts_count: 30000,
      ipd: "1ms",
      payload_size: "82 B",
      css_class: "haptic"
    },
    {
      label: "AR/VR",
      value: "vr",
      icon: "bi bi-play-btn",
      pkts_count: 11942,
      ipd: "1ns - 20ms",
      payload_size: "1328 B",
      css_class: "vr2"
    },

    {
      label: "Social Media",
      value: "social",
      icon: "bi bi-volume-up",
      pkts_count: 1200,
      ipd: "24ms",
      payload_size: "480 B",
      css_class: "social",

    },
    {
      label: "Robotic/IoT",
      value: "iot",
      icon: "bi bi-volume-up",
      pkts_count: 1200,
      ipd: "24ms",
      payload_size: "480 B",
      css_class: "gaming",

    },


  ];
  ai_models: AIModel[] = [
    {
      label: "FastInfer",
      value: "fastinfer",
      description: "",
      icon: "/assets/images/icons/fastinf.png",
      css_class: "fastinfer-card",
      isSelected: true,
      foregroundColor: "#76c893 ",
      backgroundColor: "#ecfdf5",
      accuracy: 0
    },
    {
      label: "CNN",
      value: "cnn",
      description: "",
      icon: "/assets/images/icons/cnn.png",
      css_class: "cnn-card",
      isSelected: true,
      foregroundColor: "#fb8500",
      backgroundColor: "#ffb703",

      accuracy: 0
    },
    {
      label: "GNN",
      value: "gnn",
      description: "",
      icon: "/assets/images/icons/gnn.png",
      css_class: "gnn-card",
      isSelected: false,
      foregroundColor: "#dd2d4a",
      backgroundColor: "",
      accuracy: 0
    },

    {
      label: "LSTM",
      value: "lstm",
      description: "",
      icon: "/assets/images/icons/lstm.png",
      css_class: "lstm-card",
      isSelected: false,
      foregroundColor: "#33658a",
      backgroundColor: "",
      accuracy: 0
    },

  ];


  selectedTrafficType: TrafficType = this.trafficTypes[1];
  selectedModels: AIModel[] = this.ai_models.filter(m => m.isSelected)
  sent_packets = 0;
  received_packets = 0;
  max_packets = this.trafficTypes[0].pkts_count;;
  gaugeLabel = "%";

  latency_chart_path = environment.apiUrl + "results/latency?";

  IsRunning: boolean = false;
  IsLoading: boolean = false;

  get comparisonLabel(): string {
    const selected = this.ai_models.filter(m => m.isSelected);

    if (selected.length === 0) {
      return "No models selected";
    }

    if (selected.length === 1) {
      return selected[0].label;
    }

    // Join multiple selected models with " vs "
    return selected.map(m => m.label).join(" vs ");
  }



  constructor(private backend_service: BackendService, private websocketService: WebsocketService) { }
  ngOnInit(): void {
    // Connect to the WebSocket server
    // Subscribe to received messages

    this.websocketService.listenOnMessages<Statistic>("statistics").subscribe(
      (message) => {
        // new statistic message recieved from the backend
        if (message.count_sent == 0 || message.count_recv == 0) {

        } else {

          if (message.count_sent >= this.selectedTrafficType.pkts_count) {
            message.count_sent = this.selectedTrafficType.pkts_count;
          }
          // this.update_send_packets(message.count_sent);
          // this.update_received_packets(message.count_recv);
          this.updateModelAccuracies(message);
          console.log("st:", message);

        }
      },
      (error) => {
        console.error('WebSocket error in component:', error);
      }
    );


    this.websocketService.listenOnMessages<string>("events").subscribe(
      (message) => {

        console.log('Received Event message in component:', message);
        if (message == "finished") {
          this.latency_chart_path += "2"
          this.IsRunning = false;
        }
        if (message == "update_latency_plot") {
          this.IsLoading = false;
          this.latency_chart_path += "2"

        }

        // Handle the received message (e.g., update UI)
      },
      (error) => {
        console.error('WebSocket error in component:', error);
      }
    );


  }

  sleep(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  updateModelAccuracies(stats: any) {
    Object.keys(stats).forEach(key => {
      const modelKey = key.split("_")[0];
      const model = this.ai_models.find(m => m.value === modelKey);
      if (model) {
        const acc = parseFloat(stats[key]);
        model.accuracy = isNaN(acc) ? 0 : Math.round(acc * 100); // convert 0.986 → 98
      }
    });
  }

  // async update_send_packets(value: number) {
  //   if (value < 50) {
  //     this.sent_packets = value;
  //     return;
  //   }
  //   let difference = value - this.sent_packets;
  //   let sleep_time: number = 95;
  //   let step_size: number = Math.floor(difference / 10);
  //   while (this.sent_packets < value) {
  //     await this.sleep(sleep_time);
  //     this.sent_packets = this.sent_packets + step_size;
  //   }
  //   this.sent_packets = value;

  // }
  // async update_received_packets(value: number) {

  //   if (value < 5) {
  //     this.received_packets = value;
  //     return;
  //   }

  //   let difference = value - this.received_packets;
  //   let sleep_time = 95;
  //   let step_size: number = Math.floor(difference / 10);
  //   while (this.received_packets < value) {
  //     await this.sleep(sleep_time);
  //     this.received_packets = this.received_packets + step_size;
  //   }
  //   this.received_packets = value;
  // }


  selectTrafficType(value: TrafficType) {
    this.selectedTrafficType = value;
    this.max_packets = value.pkts_count;
  }
  selectModel(value: AIModel) {
    console.log("selectModel ", value);
    value.isSelected = !value.isSelected;
    this.selectedModels = this.ai_models.filter(m => m.isSelected);
  }

  start() {
    this.IsRunning = true;
    this.IsLoading = true;

    this.backend_service.start(this.ai_models.filter(m => m.isSelected).map(item => item.value).toString(), this.selectedTrafficType.value).subscribe(data => {
      console.log("start response", data);

    });

  }
  stop() {
    this.IsRunning = false;
    this.IsLoading = false;
    this.backend_service.stop().subscribe(data => {
      console.log("stop response", data);

    });
  }







  // Example: Close the WebSocket connection
  ngOnDestroy(): void {
    this.websocketService.disconnect();
  }

}
